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
    """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_staff:
            messages.error(request, "Staff accounts cannot place orders.")
            return redirect('product:home')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@agent_required
def place_order_view(request):
    """
    Displays the main "Place Order" interface.
    This view fetches all products the agent is allowed to see.
    """

    # 1. Get all categories this user has access to
    allowed_categories = Category.objects.filter(
        user_groups__users=request.user
    )

    # 2. Get all products in those categories
    # We prefetch everything needed to calculate price and profit
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

    # 3. Serialize product data for Alpine.js
    # We only include products that have both a cost and a selling price
    product_list_json = []
    for p in products_query:
        base_cost = p.base_cost
        selling_price = p.selling_price

        # Agents can only order items with a valid cost and price
        if base_cost is not None and selling_price is not None:
            profit = selling_price - base_cost
            if profit > 0:
                product_list_json.append({
                    'id': p.id,
                    'name': p.name,
                    'sku': p.sku or '-',
                    'selling_price': selling_price,
                    'base_cost': base_cost,
                    'profit': profit,
                    'img_url': p.featured_image.image.url if p.featured_image else None,
                })

    context = {
        'products_json': json.dumps(product_list_json, default=str),
    }
    return render(request, 'order/place_order.html', context)


@agent_required
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

        # 2. Re-fetch all product data from the DB to ensure price integrity
        # This is a critical security step.
        products_in_cart = Product.objects.filter(id__in=product_ids).prefetch_related(
             Prefetch(
                'quotationitem_set',
                queryset=QuotationItem.objects.select_related('quotation')
                                              .prefetch_related('quotation__items')
                                              .order_by('-quotation__date_quoted'),
                to_attr='latest_quotation_items'
            )
        )

        product_price_map = {}
        for p in products_in_cart:
            if p.selling_price is not None and p.base_cost is not None:
                product_price_map[p.id] = {
                    'selling_price': p.selling_price,
                    'landed_cost': p.base_cost, # base_cost is the landed_cost
                }

        # 3. Validate cart and create OrderItems
        for item in cart_items:
            product_id = item.get('id')
            quantity = int(item.get('quantity', 0))

            if quantity <= 0:
                continue # Skip items with no quantity

            if product_id not in product_price_map:
                # This product was invalid (no price) or didn't exist
                raise IntegrityError(f"Product {product_id} is not orderable or does not exist.")

            price_data = product_price_map[product_id]

            items_to_create.append(
                OrderItem(
                    order=new_order,
                    product_id=product_id,
                    quantity=quantity,
                    selling_price=price_data['selling_price'],
                    landed_cost=price_data['landed_cost']
                    # The 'profit' field will be calculated on save()
                )
            )

        if not items_to_create:
            raise IntegrityError("No valid items were found in the cart.")

        # 4. Bulk create all items
        OrderItem.objects.bulk_create(items_to_create)

        # Note: The order/signals.py receiver will now fire for each
        # OrderItem created, generating the commission records.

        success_url = reverse('order:order_success', kwargs={'order_id': new_order.id})
        return JsonResponse({'success': True, 'redirect_url': success_url})

    except IntegrityError as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': f'Order processing failed: {e}'}, status=400)
    except Exception as e:
        transaction.set_rollback(True)
        return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {e}'}, status=500)


@agent_required
def order_success_view(request, order_id):
    """
    Displays a "Thank You" page after a successful order.
    """
    order = get_object_or_404(Order, id=order_id, agent=request.user)

    # Prefetch related items for display
    order_items = OrderItem.objects.filter(order=order).select_related('product')

    # Calculate totals
    subtotal = sum(item.selling_price * item.quantity for item in order_items)
    total_profit = order.total_profit # This uses the @property
    total_commission = order.total_commission # This uses the @property

    context = {
        'order': order,
        'order_items': order_items,
        'subtotal': subtotal,
        'total_profit': total_profit,
        'total_commission': total_commission,
    }
    return render(request, 'order/order_success.html', context)
