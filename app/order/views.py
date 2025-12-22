# distributorplatform/app/order/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q, Prefetch, Sum, F
import json
import uuid

from inventory.models import QuotationItem
from product.models import Product, Category
from .models import Order, OrderItem

def agent_required(view_func):
    """
    Decorator to ensure the user is logged in.
    Allows both Agents and Staff.
    """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@agent_required
def place_order_view(request):
    """
    Displays the main "Place Order" interface.
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

    is_agent = request.user.user_groups.filter(commission_percentage__gt=0).exists()

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
                'base_cost': None,
                'profit': None,
            }

            if is_agent:
                if base_cost is not None:
                    profit = selling_price - base_cost
                    if profit > 0:
                        item_data['base_cost'] = base_cost
                        item_data['profit'] = profit
                        product_list_json.append(item_data)
            else:
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

        items_created_count = 0

        # 3. Validate cart and Create Items
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

            OrderItem.objects.create(
                order=new_order,
                product=product,
                quantity=quantity,
                selling_price=product.selling_price,
                landed_cost=landed_cost
            )
            items_created_count += 1

        if items_created_count == 0:
            raise IntegrityError("No valid items were found in the cart.")

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
    """
    Displays a "Thank You" page.
    """
    order = get_object_or_404(Order, id=order_id, agent=request.user)
    order_items = OrderItem.objects.filter(order=order).select_related('product')

    subtotal = sum(item.selling_price * item.quantity for item in order_items)
    is_agent = request.user.user_groups.filter(commission_percentage__gt=0).exists()

    total_profit = order.total_profit if is_agent else None
    total_commission = order.total_commission if is_agent else None

    context = {
        'order': order,
        'order_items': order_items,
        'subtotal': subtotal,
        'total_profit': total_profit,
        'total_commission': total_commission,
        'is_agent': is_agent,
    }
    return render(request, 'order/order_success.html', context)

@staff_member_required
def manage_orders_dashboard(request):
    """Renders the dedicated Order Management Dashboard with Stats."""

    # 1. Calculate Stats
    orders = Order.objects.all()

    total_orders = orders.count()
    pending_orders = orders.filter(status=Order.OrderStatus.PENDING).count()
    completed_orders = orders.filter(status=Order.OrderStatus.COMPLETED).count()

    financials = OrderItem.objects.aggregate(
        total_revenue=Sum(F('selling_price') * F('quantity'))
        # REMOVED: total_profit aggregation
    )

    context = {
        'title': 'Manage Orders',
        'order_statuses': Order.OrderStatus.choices,
        'stats': {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
            'revenue': financials['total_revenue'] or Decimal('0.00'),
            # REMOVED: profit
        }
    }
    return render(request, 'order/manage_orders.html', context)

@staff_member_required
def api_manage_orders(request):
    """JSON API to fetch filtered and paginated orders."""
    try:
        page_number = request.GET.get('page', 1)
        limit = request.GET.get('limit', 20)
        search_query = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '')

        orders = Order.objects.select_related('agent').prefetch_related('items').order_by('-created_at')

        if status_filter:
            orders = orders.filter(status=status_filter)

        if search_query:
            # --- CHANGED: Search Logic for UUID ---
            try:
                # Try to interpret search as a UUID
                uuid_obj = uuid.UUID(search_query)
                orders = orders.filter(id=uuid_obj)
            except ValueError:
                # If not a valid UUID, search by customer name
                orders = orders.filter(agent__username__icontains=search_query)

        paginator = Paginator(orders, limit)
        page_obj = paginator.get_page(page_number)

        data = []
        for order in page_obj:
            try:
                total_items = sum(item.quantity for item in order.items.all())
                total_value = sum(item.selling_price * item.quantity for item in order.items.all())
                gross_profit = sum((item.profit or 0) for item in order.items.all())

                user_group = order.agent.user_groups.first()
                commission_rate = Decimal('0.00')
                if user_group and user_group.commission_percentage > 0:
                    commission_rate = user_group.commission_percentage / Decimal('100.00')

                total_commission = Decimal(gross_profit) * commission_rate
                is_agent = total_commission > 0

                data.append({
                    'id': str(order.id), # Convert UUID to string
                    'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
                    'customer': order.agent.username,
                    'is_agent': is_agent,
                    'status': order.get_status_display(),
                    'status_code': order.status,
                    'total_items': total_items,
                    'total_value': float(total_value),
                    'total_commission': float(total_commission),
                })
            except Exception as e:
                continue

        return JsonResponse({
            'items': data,
            'pagination': {
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'num_pages': paginator.num_pages,
                'current_page': page_obj.number,
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

        
@staff_member_required
def api_get_order_items(request, order_id):
    """JSON API to fetch items for a specific order (Accordion)."""
    order = get_object_or_404(Order, pk=order_id)
    items = order.items.select_related('product').all()

    data = []
    for item in items:
        # Keep item-level profit (Gross) if needed for debugging, or remove if strictly "no profit info".
        # Assuming removing Net Profit from dashboard means just the dashboard summary.
        # I will keep the item breakdown basic.

        data.append({
            'product_name': item.product.name,
            'sku': item.product.sku or '-',
            'quantity': item.quantity,
            'selling_price': float(item.selling_price),
            'total': float(item.selling_price * item.quantity),
            # REMOVED: 'profit': float(profit_val) - cleaning up all profit info to be safe
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

        for item in cart_items:
            p_id = item.get('id')
            quantity = int(item.get('quantity', 0))

            if quantity <= 0: continue
            if p_id not in product_map: continue

            product = product_map[p_id]
            selling_price = product.selling_price if product.selling_price is not None else Decimal('0.00')
            base_cost = product.base_cost if product.base_cost is not None else Decimal('0.00')

            profit = (selling_price - base_cost) * quantity

            checkout_cart.append({
                'product_id': product.id,
                'name': product.name,
                'sku': product.sku or '-',
                'quantity': quantity,
                'selling_price': str(selling_price),
                'base_cost': str(base_cost),
                'total_price': str(selling_price * quantity),
                'total_profit': str(profit),
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
    total_profit = Decimal('0.00')
    formatted_items = []

    for item in checkout_data:
        t_price = Decimal(item['total_price'])
        t_profit = Decimal(item['total_profit'])
        total_amount += t_price
        total_profit += t_profit

        formatted_items.append({
            **item,
            'selling_price': Decimal(item['selling_price']),
            'total_price': t_price,
            'total_profit': t_profit
        })

    is_agent = request.user.user_groups.filter(commission_percentage__gt=0).exists()

    context = {
        'items': formatted_items,
        'total_amount': total_amount,
        'total_profit': total_profit,
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

        # 2. Create Items Loop
        for item in checkout_data:
            OrderItem.objects.create(
                order=order,
                product_id=item['product_id'],
                quantity=item['quantity'],
                selling_price=Decimal(item['selling_price']),
                landed_cost=Decimal(item['base_cost'])
            )

        # 3. Clear Session
        del request.session['checkout_data']

        return JsonResponse({
            'success': True,
            'redirect_url': reverse('order:order_success', kwargs={'order_id': order.id})
        })

    except Exception as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
