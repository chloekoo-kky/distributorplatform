# distributorplatform/app/order/views.py
import csv  # Added import
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse, HttpResponse # Added HttpResponse
from django.views.decorators.csrf import csrf_exempt

from django.core.paginator import Paginator
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q, Prefetch, Max, Sum, F, DecimalField
import json
import hashlib
import urllib.parse

from inventory.models import QuotationItem
from product.models import Product, Category
from .models import Order, OrderItem
from core.models import SiteSetting, PaymentOption

def agent_required(view_func):
    """
    Decorator to ensure the user is logged in.
    """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@agent_required
def place_order_view(request):
    """
    Displays the main "Place Order" interface.
    Accessible by any logged-in user (Customer or Agent).
    """
    allowed_categories = Category.objects.filter(
        user_groups__users=request.user
    )

    products_query = Product.objects.filter(
        categories__in=allowed_categories
    ).select_related('featured_image').prefetch_related(
        Prefetch(
            'quotationitem_set',
            queryset=QuotationItem.objects.select_related('quotation')
                                          .prefetch_related('quotation__items')
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items'
        )
    ).distinct().order_by('name')

    # --- 1. Determine Agent Status ---
    # User is an 'Agent' ONLY if they belong to a group with > 0% commission.
    max_commission_data = request.user.user_groups.aggregate(Max('commission_percentage'))
    agent_commission_percent = max_commission_data['commission_percentage__max'] or Decimal('0.00')
    is_agent = agent_commission_percent > 0

    product_list_json = []
    for p in products_query:
        selling_price = p.selling_price
        base_cost = p.base_cost

        if selling_price is not None:
            item_data = {
                'id': p.id,
                'name': p.name,
                'sku': p.sku or '-',
                'selling_price': selling_price,
                'img_url': p.featured_image.image.url if p.featured_image else None,
                'commission': 0.00, # Default for customers
            }

            if is_agent:
                # --- 2. Calculate Agent's Commission ---
                # Logic: Selling Price * Profit Margin * Agent Commission %

                commission_value = Decimal('0.00')

                # A. Determine the 'Profit Base' (The pool from which commission is taken)
                if p.profit_margin is not None:
                    # Preferred: Use explicit Product Profit Margin
                    # Profit Base = Selling Price * (Product Margin / 100)
                    profit_base = selling_price * (p.profit_margin / Decimal('100.00'))
                elif base_cost is not None:
                    # Fallback: Use actual Gross Profit (Selling - Cost) if margin is missing
                    profit_base = selling_price - base_cost
                else:
                    profit_base = Decimal('0.00')

                # B. Apply Agent's Commission Percentage
                # Commission = Profit Base * (Agent Group % / 100)
                if profit_base > 0:
                    commission_value = profit_base * (agent_commission_percent / Decimal('100.00'))

                item_data['commission'] = commission_value

            product_list_json.append(item_data)

    context = {
        'products_json': product_list_json,
        'is_agent': is_agent,
    }
    return render(request, 'order/place_order.html', context)


@login_required
@transaction.atomic
def api_submit_order(request):
    """
    API endpoint to receive the cart data and create an order.
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])

        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Your cart is empty.'}, status=400)

        # 1. Create the parent Order
        new_order = Order.objects.create(
            agent=request.user,
            status=Order.OrderStatus.PENDING
        )

        items_to_create = []
        product_ids = [item.get('id') for item in cart_items]

        # 2. Re-fetch products to get current prices (Security)
        products_in_cart = Product.objects.filter(id__in=product_ids).prefetch_related(
             Prefetch(
                'quotationitem_set',
                queryset=QuotationItem.objects.select_related('quotation')
                                              .prefetch_related('quotation__items')
                                              .order_by('-quotation__date_quoted'),
                to_attr='latest_quotation_items'
            )
        )

        product_map = {p.id: p for p in products_in_cart}

        # 3. Validate cart
        for item in cart_items:
            product_id = item.get('id')
            quantity = int(item.get('quantity', 0))

            if quantity <= 0: continue

            if product_id not in product_map:
                raise IntegrityError(f"Product {product_id} unavailable.")

            product = product_map[product_id]

            if product.selling_price is None:
                raise IntegrityError(f"Product {product.name} has no selling price.")

            landed_cost = product.base_cost if product.base_cost is not None else Decimal('0.00')

            items_to_create.append(
                OrderItem(
                    order=new_order,
                    product=product,
                    quantity=quantity,
                    selling_price=product.selling_price,
                    landed_cost=landed_cost
                )
            )

        if not items_to_create:
            raise IntegrityError("No valid items were found in the cart.")

        # --- FIX: Use save() in a loop instead of bulk_create to trigger signals ---
        # OrderItem.objects.bulk_create(items_to_create) <--- REPLACED
        for item in items_to_create:
            item.save()
        # --------------------------------------------------------------------------

        success_url = reverse('order:order_success', kwargs={'order_id': new_order.id})
        return JsonResponse({'success': True, 'redirect_url': success_url})

    except IntegrityError as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': f'Order processing failed: {e}'}, status=400)
    except Exception as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {e}'}, status=500)


@login_required
def order_success_view(request, order_id):
    order = get_object_or_404(Order, id=order_id, agent=request.user)

    # Calculate totals for the template (if not already done by model)
    order_items = order.items.select_related('product')
    subtotal = sum(item.total_price for item in order_items)

    # --- ADD THIS BLOCK: Prepare WhatsApp Message ---
    site_settings = SiteSetting.load()
    cs_phone = site_settings.customer_service_whatsapp

    # Build the message line by line
    msg_lines = [
        f"*New Order Placed!*",
        f"Order ID: #{order.id}",
        f"Agent: {request.user.username}",
        f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        "*Items:*",
    ]

    for item in order_items:
        msg_lines.append(f"- {item.product.name} (x{item.quantity})")

    msg_lines.append("")
    msg_lines.append(f"*Total Amount: RM {subtotal:.2f}*")
    msg_lines.append(f"Status: {order.get_status_display()}")

    # Join and encode for URL
    full_message = "\n".join(msg_lines)
    encoded_message = urllib.parse.quote(full_message)
    whatsapp_url = f"https://wa.me/{cs_phone}?text={encoded_message}"

    context = {
        'order': order,
        'order_items': order_items,
        'subtotal': subtotal,
        'whatsapp_url': whatsapp_url, # Pass to template
    }
    return render(request, 'order/order_success.html', context)

@staff_member_required
def manage_orders_dashboard(request):
    """Renders the dedicated Order Management Dashboard with Statistics."""

    # 1. Calculate Statistics
    orders = Order.objects.all()

    # UPDATED: Total Orders excludes CANCELLED
    total_orders = orders.exclude(status=Order.OrderStatus.CANCELLED).count()

    # Count "Pending Action" as anything NOT Completed or Cancelled
    pending_orders = orders.exclude(status__in=[
        Order.OrderStatus.COMPLETED,
        Order.OrderStatus.CANCELLED
    ]).count()

    completed_orders = orders.filter(status=Order.OrderStatus.COMPLETED).count()

    # Calculate Total Revenue
    revenue = Decimal('0.00')
    if request.user.is_superuser:
        financials = OrderItem.objects.exclude(order__status=Order.OrderStatus.CANCELLED).aggregate(
            total_revenue=Sum(F('selling_price') * F('quantity'), output_field=DecimalField())
        )
        revenue = financials['total_revenue'] or Decimal('0.00')

    context = {
        'title': 'Manage Orders',
        'order_statuses': Order.OrderStatus.choices,
        'stats': {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
            'revenue': revenue,
        }
    }
    return render(request, 'order/manage_orders.html', context)


@staff_member_required
def api_manage_orders(request):
    """JSON API to fetch filtered and paginated orders."""
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 20)
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')

    orders = Order.objects.select_related('agent').prefetch_related('items').order_by('-created_at')

    if status_filter:
        orders = orders.filter(status=status_filter)

    # --- UPDATED SEARCH LOGIC ---
    if search_query:
        # Search by ID (contains) OR Username (contains)
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(agent__username__icontains=search_query)
        )

    paginator = Paginator(orders, limit)
    page_obj = paginator.get_page(page_number)

    data = []
    for order in page_obj:
        total_items = sum(item.quantity for item in order.items.all())
        total_value = sum(item.selling_price * item.quantity for item in order.items.all())
        gross_profit = sum(item.profit for item in order.items.all())

        data.append({
            'id': order.id,
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
            'agent': order.agent.username,
            'customer': str(order.agent.username) if hasattr(order, 'is_agent_order') and order.is_agent_order else order.agent.username,
            'is_agent': False,
            'status': order.get_status_display(),
            'status_code': order.status,
            'total_items': total_items,
            'total_value': float(total_value),
            'total_profit': float(gross_profit),
            'total_commission': float(order.total_commission),
        })

    # --- UPDATED: Stats to include all non-terminal statuses in "Pending Action" and Exclude Cancelled from Total ---
    stats = {
        'total_orders': Order.objects.exclude(status=Order.OrderStatus.CANCELLED).count(),
        'pending_orders': Order.objects.exclude(status__in=[
            Order.OrderStatus.COMPLETED,
            Order.OrderStatus.CANCELLED
        ]).count(),
        'completed_orders': Order.objects.filter(status=Order.OrderStatus.COMPLETED).count(),
        'revenue': 0,
    }

    if request.user.is_superuser:
        rev_agg = OrderItem.objects.exclude(order__status=Order.OrderStatus.CANCELLED).aggregate(
            t=Sum(F('selling_price') * F('quantity'), output_field=DecimalField())
        )
        stats['revenue'] = float(rev_agg['t'] or 0)

    return JsonResponse({
        'items': data,
        'pagination': {
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'num_pages': paginator.num_pages,
            'current_page': page_obj.number,
        },
        'stats': stats
    })

@staff_member_required
def api_get_order_items(request, order_id):
    """JSON API to fetch items for a specific order (Accordion)."""
    order = get_object_or_404(Order, pk=order_id)
    items = order.items.select_related('product').all()

    data = []
    for item in items:
        data.append({
            'product_name': item.product.name,
            'sku': item.product.sku or '-',
            'quantity': item.quantity,
            'selling_price': float(item.selling_price),
            'total': float(item.selling_price * item.quantity),
            'profit': float(item.profit),
        })

    return JsonResponse({'items': data})

@staff_member_required
@transaction.atomic
def api_update_order_status(request, order_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=400)

    try:
        data = json.loads(request.body)
        new_status = data.get('status')

        if new_status not in Order.OrderStatus.values:
             return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)

        order = get_object_or_404(Order, pk=order_id)
        order.status = new_status
        order.save()

        return JsonResponse({'success': True, 'message': 'Status updated'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def api_prepare_checkout(request):
    """
    Receives cart JSON, validates items/prices, and stores the checkout payload in Session.
    """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])

        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Cart is empty.'}, status=400)

        product_ids = [item.get('id') for item in cart_items]
        products = Product.objects.filter(id__in=product_ids)
        product_map = {p.id: p for p in products}

        checkout_cart = []

        # Recalculate agent commission for session storage
        max_commission_data = request.user.user_groups.aggregate(Max('commission_percentage'))
        agent_commission_percent = max_commission_data['commission_percentage__max'] or Decimal('0.00')
        is_agent = agent_commission_percent > 0

        for item in cart_items:
            p_id = item.get('id')
            quantity = int(item.get('quantity', 0))

            if quantity <= 0: continue
            if p_id not in product_map: continue

            product = product_map[p_id]
            selling_price = product.selling_price if product.selling_price is not None else Decimal('0.00')
            base_cost = product.base_cost if product.base_cost is not None else Decimal('0.00')

            # Calculate Agent Commission
            estimated_commission = Decimal('0.00')
            if is_agent:
                if product.profit_margin is not None:
                    profit_base = selling_price * (product.profit_margin / Decimal('100.00'))
                elif base_cost is not None:
                    profit_base = selling_price - base_cost
                else:
                    profit_base = Decimal('0.00')

                if profit_base > 0:
                    estimated_commission = (profit_base * (agent_commission_percent / Decimal('100.00'))) * quantity

            checkout_cart.append({
                'product_id': product.id,
                'name': product.name,
                'sku': product.sku or '-',
                'quantity': quantity,
                'selling_price': str(selling_price),
                'base_cost': str(base_cost),
                'total_price': str(selling_price * quantity),
                'total_commission': str(estimated_commission),
                'img_url': product.featured_image.image.url if product.featured_image else None
            })

        if not checkout_cart:
            return JsonResponse({'success': False, 'error': 'No valid products found.'}, status=400)

        request.session['checkout_data'] = checkout_cart
        return JsonResponse({'success': True, 'redirect_url': reverse('order:checkout_confirmation')})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def checkout_confirmation_view(request):
    """
    Displays the Checkout Confirmation page using data from Session.
    """
    checkout_data = request.session.get('checkout_data')

    if not checkout_data:
        messages.error(request, "Your checkout session has expired. Please try again.")
        return redirect('order:place_order')

    total_amount = Decimal('0.00')
    total_commission = Decimal('0.00')
    formatted_items = []

    for item in checkout_data:
        t_price = Decimal(item['total_price'])
        t_comm = Decimal(item.get('total_commission', item.get('total_profit', '0.00')))

        total_amount += t_price
        total_commission += t_comm

        formatted_items.append({
            **item,
            'selling_price': Decimal(item['selling_price']),
            'total_price': t_price,
            'total_commission': t_comm
        })

    is_agent = request.user.user_groups.filter(commission_percentage__gt=0).exists()

    context = {
        'items': formatted_items,
        'total_amount': total_amount,
        'total_commission': total_commission,
        'is_agent': is_agent
    }
    return render(request, 'order/checkout.html', context)


@login_required
@transaction.atomic
def api_confirm_checkout(request):
    """
    Finalizes the order using the data stored in Session.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    checkout_data = request.session.get('checkout_data')
    if not checkout_data:
        return JsonResponse({'success': False, 'error': 'Session expired.'}, status=400)

    try:
        # 1. Create Parent Order
        order = Order.objects.create(
            agent=request.user,
            status=Order.OrderStatus.PENDING
        )

        items_to_create = []

        # 2. Create Items from Session Data
        for item in checkout_data:
            qty = int(item['quantity'])
            sp = Decimal(item['selling_price'])
            lc = Decimal(item['base_cost'])

            db_profit = (sp - lc) * qty

            items_to_create.append(OrderItem(
                order=order,
                product_id=item['product_id'],
                quantity=qty,
                selling_price=sp,
                landed_cost=lc,
                profit=db_profit
            ))

        # --- FIX: Use save() in loop to trigger signals for each item ---
        # OrderItem.objects.bulk_create(items_to_create) <--- REPLACED
        for item in items_to_create:
            item.save()
        # ---------------------------------------------------------------

        # 3. Clear Session
        del request.session['checkout_data']

        return JsonResponse({
            'success': True,
            'redirect_url': reverse('order:order_success', kwargs={'order_id': order.id})
        })

    except Exception as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def payment_view(request, order_id):
    """
    Handles payment selection. Expects POST from the profile modal.
    """
    order = get_object_or_404(Order, id=order_id, agent=request.user)

    if order.status != Order.OrderStatus.TO_PAY:
        messages.error(request, "This order is not eligible for payment.")
        return redirect('user:profile')

    if request.method == 'POST':
        method_id = request.POST.get('payment_method_id')
        try:
            payment_option = PaymentOption.objects.get(id=method_id, is_active=True)
        except (PaymentOption.DoesNotExist, ValueError):
            messages.error(request, "Invalid payment method selected.")
            return redirect('user:profile')

        # Logic Branching based on Option Type
        if payment_option.option_type == 'GATEWAY':
            # --- Existing Gateway Logic ---
            amount_rm = sum(item.selling_price * item.quantity for item in order.items.all())
            if amount_rm <= 0:
                messages.error(request, "Invalid order amount.")
                return redirect('user:profile')

            config = SiteSetting.objects.first()
            if not config or not config.payment_enabled:
                messages.error(request, "Online payments are currently disabled in settings.")
                return redirect('user:profile')

            if config.payment_provider == 'SENANGPAY':
                return _initiate_order_senangpay(request, order, amount_rm, config)
            else:
                messages.error(request, f"Provider {config.payment_provider} not supported.")
                return redirect('user:profile')

        elif payment_option.option_type == 'COD':
            # --- Cash On Delivery Logic ---
            order.payment_method = payment_option.name
            order.status = Order.OrderStatus.TO_SHIP
            order.save()
            messages.success(request, f"Order confirmed! Payment method: {payment_option.name}. Please pay upon delivery.")
            return redirect('user:profile')

        elif payment_option.option_type == 'MANUAL':
             # --- Manual / Bank Transfer Logic ---
            order.payment_method = payment_option.name
            order.status = Order.OrderStatus.TO_SHIP
            order.save()
            messages.success(request, f"Order submitted. Please follow the instructions for {payment_option.name}.")
            return redirect('user:profile')

    messages.error(request, "Invalid request method.")
    return redirect('user:profile')


def _initiate_order_senangpay(request, order, amount_rm, config):
    # SenangPay requires the amount in standard decimal format (e.g., 10.00)
    amount_str = f"{amount_rm:.2f}"

    # 1. Clean inputs (Strip whitespace)
    merchant_id = str(config.payment_category_code).strip()
    secret_key = str(config.payment_api_key).strip()

    detail = f"Order_{order.id}"
    order_id_ref = str(order.id)

    # 2. Calculate Hash
    data_to_hash = f"{secret_key}{detail}{amount_str}{order_id_ref}"
    hashed_value = hashlib.md5(data_to_hash.encode()).hexdigest()

    name = order.agent.username
    email = order.agent.email
    phone = str(order.agent.phone_number).replace('+', '') if order.agent.phone_number else ''

    params = {
        'detail': detail,
        'amount': amount_str,
        'order_id': order_id_ref,
        'name': name,
        'email': email,
        'phone': phone,
        'hash': hashed_value,
    }

    query_string = urllib.parse.urlencode(params)

    # 3. Construct URL robustly
    base_url = config.payment_gateway_url.strip().rstrip('/')
    payment_url = f"{base_url}/{merchant_id}?{query_string}"

    return redirect(payment_url)


def payment_callback_view(request):
    """
    User returns here after payment via SenangPay (Redirect URL).
    GET params: status_id, order_id, msg, transaction_id, hash
    """
    status_id = request.GET.get('status_id')  # '1' = Success, '0' = Fail
    order_id = request.GET.get('order_id')
    msg = request.GET.get('msg')
    transaction_id = request.GET.get('transaction_id')
    received_hash = request.GET.get('hash')

    config = SiteSetting.objects.first()
    secret_key = str(config.payment_api_key).strip()

    data_to_verify = f"{secret_key}{status_id}{order_id}{transaction_id}{msg}"
    expected_hash = hashlib.md5(data_to_verify.encode()).hexdigest()

    if received_hash != expected_hash:
        messages.error(request, "Security verification failed (Invalid Hash).")
        return redirect('user:profile')

    if status_id == '1':
        try:
            order = Order.objects.get(id=order_id)
            if order.status == Order.OrderStatus.TO_PAY:
                order.status = Order.OrderStatus.TO_SHIP
                order.save()
                messages.success(request, f"Payment successful! Order #{order.id} is now being processed.")
            else:
                messages.info(request, f"Order #{order.id} payment status check completed.")
        except Order.DoesNotExist:
            messages.error(request, "Order not found during payment callback.")
    else:
        messages.error(request, f"Payment failed: {msg}")

    return redirect('user:profile')


@csrf_exempt
def payment_webhook_view(request):
    """
    Server-to-server update from SenangPay (Webhook).
    POST params: status_id, order_id, msg, transaction_id, hash
    """
    if request.method == 'POST':
        data = request.POST
        status_id = data.get('status_id')
        order_id = data.get('order_id')
        msg = data.get('msg')
        transaction_id = data.get('transaction_id')
        received_hash = data.get('hash')

        config = SiteSetting.objects.first()
        secret_key = str(config.payment_api_key).strip()
        data_to_verify = f"{secret_key}{status_id}{order_id}{transaction_id}{msg}"
        expected_hash = hashlib.md5(data_to_verify.encode()).hexdigest()

        if received_hash != expected_hash:
            return HttpResponse("Invalid Hash", status=403)

        try:
            order = Order.objects.get(id=order_id)
            if status_id == '1' and order.status == Order.OrderStatus.TO_PAY:
                order.status = Order.OrderStatus.TO_SHIP
                order.save()
            return HttpResponse("OK")
        except Order.DoesNotExist:
            return HttpResponse("Order Not Found", status=404)

    return HttpResponse("Invalid Method", status=405)

# --- NEW: Export Order Statement View ---
@staff_member_required
def export_order_statement(request):
    """
    Export orders to CSV based on Month/Year.
    Rows are split by Order Item.
    Order Total is only shown on the LAST item row of each order.
    """
    try:
        month = int(request.GET.get('month', timezone.now().month))
        year = int(request.GET.get('year', timezone.now().year))
        status = request.GET.get('status', '')

        # Filter by Month/Year
        orders = Order.objects.filter(
            created_at__year=year,
            created_at__month=month
        ).select_related('agent').prefetch_related('items__product').order_by('created_at')

        # Optional Status Filter
        if status:
            orders = orders.filter(status=status)

        # Prepare Response
        response = HttpResponse(content_type='text/csv')
        filename = f"order_statement_{year}_{month:02d}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        # Header Row
        writer.writerow([
            'Date', 'Order ID', 'Customer', 'Type', 'Status', 'Payment Method',
            'Product Name', 'SKU', 'Quantity', 'Unit Price (RM)', 'Line Total (RM)', 'Order Total (RM)'
        ])

        for order in orders:
            is_agent = order.agent.user_groups.filter(commission_percentage__gt=0).exists()
            user_type = "Agent" if is_agent else "Customer"

            # Fetch all items to a list to check length
            items = list(order.items.all())
            order_total = sum(item.selling_price * item.quantity for item in items)
            total_items_count = len(items)

            for index, item in enumerate(items):
                line_total = item.selling_price * item.quantity

                # --- LOGIC UPDATE: Show Order Total ONLY on the LAST row ---
                if index == total_items_count - 1:
                    row_order_total = f"{order_total:.2f}"
                else:
                    row_order_total = "" # Empty for previous rows

                writer.writerow([
                    order.created_at.strftime('%Y-%m-%d %H:%M'),
                    order.id,
                    order.agent.username,
                    user_type,
                    order.get_status_display(),
                    order.payment_method or "-",
                    item.product.name,
                    item.product.sku or "-",
                    item.quantity,
                    f"{item.selling_price:.2f}",
                    f"{line_total:.2f}",
                    row_order_total  # Only populated for last item
                ])

        return response

    except Exception as e:
        return HttpResponse(f"Error exporting CSV: {str(e)}", status=500)
