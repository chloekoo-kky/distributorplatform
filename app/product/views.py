# distributorplatform/app/product/views.py
from django.shortcuts import render
from .models import Product, Category

def product_list(request):
    """
    This view retrieves and displays products based on the user's group permissions.
    - If the user is not authenticated, it shows only non-members-only products.
    - If the user is authenticated, it shows products from the categories
      assigned to their user group(s).
    - If a user is in a group with no assigned categories, they won't see any products.
    """
    if request.user.is_authenticated:
        # Get all categories assigned to the user's groups
        allowed_categories = Category.objects.filter(user_groups__users=request.user).distinct()

        # Filter products that are in the allowed categories
        products = Product.objects.filter(categories__in=allowed_categories).distinct()
    else:
        # For anonymous users, only show products that are not members-only
        products = Product.objects.filter(members_only=False)

    context = {
        'products': products
    }
    return render(request, 'product/product_list.html', context)
