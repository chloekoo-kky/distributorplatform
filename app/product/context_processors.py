# distributorplatform/app/product/context_processors.py
from .models import Product, Category

def category_nav_context(request):
    """
    Provides a context processor to make the category navigation
    data available on all pages.
    """
    selected_category_code = request.GET.get('category')
    allowed_categories_list = None

    if request.user.is_authenticated and not request.user.is_anonymous:
        # Get all categories assigned to the user's groups
        allowed_categories_list = Category.objects.filter(
            user_groups__users=request.user
        ).select_related('group').distinct().order_by('name')
    else:
        # For anonymous users, get products first
        products_query = Product.objects.filter(members_only=False)
        # Find all categories that contain at least one of these products
        allowed_categories_list = Category.objects.filter(
            products__in=products_query
        ).select_related('group').distinct().order_by('name')

    return {
        'allowed_categories_list': allowed_categories_list,
        'selected_category_code': selected_category_code,
    }
