from django.shortcuts import render

# Create your views here.
# distributorplatform/app/order/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse
import json

from inventory.models import QuotationItem
from product.models import Product, Category
from .models import Order, OrderItem

from django.db.models import Q, Prefetch

def agent_required(view_func):
    """
    Decorator to ensure the user is logged in AND is NOT a staff member.
    (MODIFIED to allow staff)
    """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        # --- START MODIFICATION ---
        # The following 'if' block has been removed to allow staff access
        # if request.user.is_staff:
        #     messages.error(request, "Staff accounts cannot place orders.")
        #     return redirect('product:home')
        # --- END MODIFICATION ---
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@agent_required
def place_order_view(request):
    """
    Displays the main "Place Order" interface.
    Accessible by any logged-in user (Customer or Agent).
    """

    # 1. Get all categories this user has access to
    allowed_categories = Category.objects.filter(
        user_groups__users=request.user
    )

    # 2. Get all products in those categories
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

    # --- Check User Role ---
    is_agent = request.user.user_groups.filter(commission_percentage__gt=0).exists()

    # 3. Serialize product data
    product_list_json = []
    for p in products_query:
        selling_price = p.selling_price
        base_cost = p.base_cost

        # Logic for including product in the list
        if selling_price is not None:
            item_data = {
                'id': p.id,
                'name': p.name,
                'sku': p.sku or '-',
                'selling_price': selling_price,
                'img_url': p.featured_image.image.url if p.featured_image else None,
                # Default sensitive fields to None
                'base_cost': None,
                'profit': None,
            }

            if is_agent:
                # Agents need base_cost to calculate profit
                if base_cost is not None:
                    profit = selling_price - base_cost
                    if profit > 0:
                        item_data['base_cost'] = base_cost
                        item_data['profit'] = profit
                        product_list_json.append(item_data)
            else:
                # Customers just need selling_price
                # We purposefully DO NOT include base_cost/profit in JSON for customers
                product_list_json.append(item_data)

    context = {
        'products_json': product_list_json, # Passed raw, template uses |json_script
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

            # Validate Price exists
            if product.selling_price is None:
                raise IntegrityError(f"Product {product.name} has no selling price.")

            # For landed_cost, use base_cost if exists, else 0 (for profit calc)
            landed_cost = product.base_cost if product.base_cost is not None else Decimal('0.00')

            items_to_create.append(
                OrderItem(
                    order=new_order,
                    product_id=product_id,
                    quantity=quantity,
                    selling_price=product.selling_price,
                    landed_cost=landed_cost
                )
            )

        if not items_to_create:
            raise IntegrityError("No valid items were found in the cart.")

        OrderItem.objects.bulk_create(items_to_create)

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

    # Only calculate profit/commission for display if they are an Agent
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
