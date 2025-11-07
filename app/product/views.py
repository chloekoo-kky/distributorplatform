# distributorplatform/app/product/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from tablib import Dataset
import datetime
import logging
import json
from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Q, Subquery, OuterRef, Sum, Prefetch
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage
from inventory.models import QuotationItem
from inventory.views import staff_required

from .models import Product, Category, CategoryGroup
from .forms import ProductUploadForm, ProductForm # Import new ProductForm
from .resources import ProductResource
from blog.models import Post
from blog.views import get_accessible_posts
from product.models import Product, Category, CategoryGroup
from images.models import MediaImage, ImageCategory
from images.forms import ImageUploadForm # Re-use this form


logger = logging.getLogger(__name__)


def home(request):
    """
    Renders the new site home page.
    """
    # --- START MODIFICATION ---
    # Query changed from 'image__isnull' to 'featured_image__isnull'
    featured_products = Product.objects.filter(
        featured_image__isnull=False,
    ).select_related('featured_image').order_by('-created_at')[:4]
    # --- END MODIFICATION ---

    # Get 3 most recent PUBLISHED posts
    latest_posts = Post.objects.filter(
        status=Post.PostStatus.PUBLISHED
    ).order_by('-created_at')[:3]

    latest_posts = get_accessible_posts(request.user).order_by('-created_at')[:3]

    context = {
        'featured_products': featured_products,
        'latest_posts': latest_posts, # <-- ADD THIS
    }
    return render(request, 'product/home.html', context)


def staff_required(view_func):
    """
    Decorator to ensure the user is logged in AND is a staff member.
    """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You do not have permission to access this page.")
            return redirect('product_list')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# Note: product_list view is no longer staff_required by default,
# so that anonymous users and non-staff can see it.
# The controls for upload/export will be hidden in the template.
def product_list(request):
    """
    This view retrieves and displays products based on the user's group permissions.
    - The category list for navigation is now provided by a context processor.
    - This view just filters the products shown on the page.
    """
    # --- START MODIFICATIONS ---
    # We still need the code to filter the product queryset
    selected_category_code = request.GET.get('category')

    # This logic determines which products to show
    products_query = None
    if request.user.is_authenticated and not request.user.is_anonymous:
        # User must have access to the category to see products in it.
        allowed_categories = Category.objects.filter(
            user_groups__users=request.user
        )
        products_query = Product.objects.filter(categories__in=allowed_categories).distinct()
    else:
        # For anonymous users, start with non-members-only products
        products_query = Product.objects.filter(members_only=False)

    # Apply filtering based on GET parameters
    if selected_category_code:
        products_query = products_query.filter(categories__code=selected_category_code)

    # --- Updated query to prefetch featured_image ---
    products = products_query.select_related(
        'featured_image'
    ).distinct().order_by('name') # Get the final product list
    # --- END MODIFICATION ---

    product_upload_form = ProductUploadForm()

    context = {
        'products': products,
        'product_upload_form': product_upload_form,
        # The context processor now handles these:
        # 'allowed_categories_list': allowed_categories_list,
        # 'selected_category_code': selected_category_code,
    }
    # --- END MODIFICATIONS ---
    return render(request, 'product/product_list.html', context)


@staff_required
def upload_products(request):
    """
    View for uploading product files.
    Processes POST requests from the modal on the product_list page.
    """
    logger.info("[upload_products] View called.")
    if request.method != 'POST':
        logger.warning("[upload_products] GET request received, redirecting.")
        return redirect('product_list')

    form = ProductUploadForm(request.POST, request.FILES)
    if form.is_valid():
        file = request.FILES['file']
        logger.info(f"[upload_products] Form is valid. Processing file: {file.name}")

        if not file.name.endswith(('.csv', '.xls', '.xlsx')):
            logger.warning(f"[upload_products] Invalid file format: {file.name}")
            messages.error(request, "Invalid file format. Please upload a .csv, .xls, or .xlsx file.")
            return redirect('product_list')

        try:
            dataset = Dataset()
            if file.name.endswith('.csv'):
                logger.info(f"[upload_products] Reading .csv file: {file.name}")
                file_content = file.read()
                decoded_content = None
                try:
                    decoded_content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    logger.warning("[upload_products] 'utf-8' decoding failed. Trying 'latin-1'.")
                    decoded_content = file_content.decode('latin-1')
                dataset.load(decoded_content, format='csv')
            else:
                logger.info(f"[upload_products] Reading .xlsx file: {file.name}")
                dataset.load(file.read(), format='xlsx')
            logger.info("[upload_products] File read and loaded into dataset.")
        except Exception as e:
            logger.error(f"[upload_products] Error reading file: {e}", exc_info=True)
            messages.error(request, f"Error reading file: {e}")
            return redirect('product_list')

        product_resource = ProductResource()
        logger.info("[upload_products] Starting dry run of import...")
        result = product_resource.import_data(dataset, dry_run=True, use_transactions=True)

        if not result.has_errors() and not result.has_validation_errors():
            try:
                logger.info("[upload_products] Dry run successful. Starting actual import.")
                with transaction.atomic():
                    product_resource.import_data(dataset, dry_run=False, use_transactions=True)
                logger.info("[upload_products] Import successful.")
                messages.success(request, "Product file imported successfully.")
            except Exception as e:
                logger.error(f"[upload_products] Error during final import: {e}", exc_info=True)
                messages.error(request, f"An error occurred during import: {e}")
        else:
            errors = result.has_errors() and result.row_errors() or result.base_errors
            logger.warning(f"[upload_products] Dry run failed. Errors: {errors}")
            if errors:
                for error in errors:
                    if error[1]:
                        msg = f"Error in row {error[0]}: {error[1][0].error}"
                        logger.warning(f"[upload_products] Import error detail: {msg}")
                        messages.warning(request, msg)
            else:
                logger.error("[upload_products] Unknown validation error occurred.")
                messages.error(request, "An unknown error occurred during validation.")
            messages.error(request, "File import failed. Please correct the file and try again.")

        return redirect('product_list')

    logger.warning(f"[upload_products] Form was invalid. Errors: {form.errors.as_json()}")
    messages.error(request, "An error occurred with the upload form.")
    return redirect('product_list')


@staff_required
def export_products_csv(request):
    """
    Handles the export of all products to a CSV file.
    """
    logger.info("[export_products_csv] View called. Starting export.")
    try:
        product_resource = ProductResource()
        queryset = Product.objects.all()
        dataset = product_resource.export(queryset)

        response = HttpResponse(dataset.csv, content_type='text/csv')
        filename = f"products-{datetime.date.today()}.csv"
        response['Content-Disposition'] = f'attachment; filename={filename}'
        logger.info(f"[export_products_csv] Successfully created CSV file: {filename}")
        return response
    except Exception as e:
        logger.error(f"[export_products_csv] Error during export: {e}", exc_info=True)
        messages.error(request, f"An error occurred during export: {e}")
        return redirect('product_list')

# --- START NEW VIEW ---
@staff_required
def manage_product_edit(request, product_id):
    """
    Handles fetching product data (GET) and updating product data (POST)
    for the product edit modal via AJAX.
    """
    product = get_object_or_404(Product.objects.prefetch_related('featured_image'), pk=product_id)

    # Handle AJAX POST request (form submission)
    if request.method == 'POST':

        # --- ADD THIS LOG ---
        logger.info(f"--- [SERVER] manage_product_edit POST received for product {product_id} ---")
        logger.info(f"[SERVER] request.POST data: {request.POST.dict()}")
        logger.info(f"[SERVER] request.FILES data: {request.FILES.dict()}")
        # --- END ADD ---

        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
             messages.error(request, "Invalid request type.")
             return redirect('core:manage_dashboard')

        form = ProductForm(request.POST, request.FILES, instance=product)

        if form.is_valid():
            try:
                form.save()
                logger.info(f"Product {product.sku} updated successfully via modal.")
                return JsonResponse({'success': True})
            except Exception as e:
                logger.error(f"Error saving product {product.sku}: {e}")
                return JsonResponse({'success': False, 'errors': {'__all__': [str(e)]}}, status=500)
        else:
            # --- THIS IS THE CRITICAL LOG ---
            logger.error(f"[SERVER] Product form is INVALID. Errors: {form.errors.as_json(escape_html=True)}")
            # --- END ADD ---
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    # Handle AJAX GET request (populating the modal)
    elif request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # ... (rest of GET logic is fine)
        data = {
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'description': product.description,
            'members_only': product.members_only,
            'categories': list(product.categories.all().values_list('id', flat=True)),
            'suppliers': list(product.suppliers.all().values_list('id', flat=True)),
            'gallery_images': list(product.gallery_images.all().values_list('id', flat=True)),
            'featured_image': product.featured_image_id, # Send just the ID
            'selectedImageUrl': product.featured_image.image.url if product.featured_image else '',
            'update_url': reverse('product:manage_product_edit', kwargs={'product_id': product.id})
        }

        logger.debug(f"--- [DEBUG] manage_product_edit (GET) for product {product_id} ---")
        logger.debug(f"[DEBUG] Sending categories: {data['categories']} (Type of first item: {type(data['categories'][0]) if data['categories'] else 'N/A'})")
        logger.debug(f"[DEBUG] Sending suppliers: {data['suppliers']} (Type of first item: {type(data['suppliers'][0]) if data['suppliers'] else 'N/A'})")

        return JsonResponse(data)

    # Fallback for non-AJAX GET (though it shouldn't be used anymore)
    messages.error(request, "Invalid request.")
    return redirect('core:manage_dashboard')


@staff_required
def api_manage_products(request):
    # Add header check
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Filters ---
    search_query = request.GET.get('search', '')
    group_filter = request.GET.get('group', '')
    category_filter = request.GET.get('category', '')
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 50) # <-- Add limit parameter

    # --- 2. Build Base Queryset ---
    queryset = Product.objects.annotate(
        # --- START REMOVAL ---
        # annotated_base_cost=Subquery(latest_item_price_sq) # <-- *** ADD THIS ANNOTATION ***
        # --- END REMOVAL ---
    ).select_related('featured_image').prefetch_related(
        Prefetch('categories', queryset=Category.objects.select_related('group')),

        # --- START ADDITION (This prefetch works with the property change) ---
        Prefetch(
            'quotationitem_set',
            queryset=QuotationItem.objects.select_related('quotation')
                                          .prefetch_related('quotation__items')
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items' # This must match the property check
        )
        # --- END ADDITION ---

    ).order_by('name')

    # --- 3. Apply Filters ---
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) | Q(sku__icontains=search_query)
        )
    if group_filter:
        queryset = queryset.filter(categories__group__name=group_filter)
    if category_filter:
        queryset = queryset.filter(categories__name=category_filter)

    queryset = queryset.distinct()

    # --- 4. Paginate ---
    paginator = Paginator(queryset, limit) # <-- Use limit variable
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    # --- 5. Serialize ---
    serialized_products = []
    for product in page_obj.object_list:
        category_list = [cat.name for cat in product.categories.all()]
        group_list = [cat.group.name for cat in product.categories.all() if cat.group]

        product_data = {
            'id': product.pk,
            'sku': product.sku or '-',
            'name': product.name,
            'selling_price': product.selling_price,

            # --- START ADDITIONS ---
            'profit_margin': product.profit_margin,
            'base_cost': product.base_cost, # This now calls the optimized @property
            # --- END ADDITIONS ---

            'category_groups': sorted(list(set(group_list))),

            # --- START ADDITION ---
            'categories': sorted(list(set(category_list))),
            # --- END ADDITION ---

            'featured_image_url': product.featured_image.image.url if product.featured_image else None,
            'featured_image_alt': product.featured_image.alt_text if product.featured_image else product.name,
            'gallery_image_ids': list(product.gallery_images.all().values_list('id', flat=True))
        }
        serialized_products.append(product_data)

    # --- 6. Return JSON ---
    return JsonResponse({
        'items': serialized_products,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })


from decimal import Decimal, InvalidOperation

@staff_required
def api_manage_pricing(request, product_id):
    """
    Handles updating the profit_margin and selling_price for a product.
    """
    if not (request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    product = get_object_or_404(Product, pk=product_id)

    try:
        data = json.loads(request.body)
        selling_price_str = data.get('selling_price')
        profit_margin_str = data.get('profit_margin')

        # Update fields only if they are provided, allowing null
        product.selling_price = Decimal(selling_price_str) if selling_price_str is not None else None
        product.profit_margin = Decimal(profit_margin_str) if profit_margin_str is not None else None

        product.save(update_fields=['selling_price', 'profit_margin'])

        logger.info(f"Updated pricing for Product {product_id}: Price={product.selling_price}, Margin={product.profit_margin}")
        return JsonResponse({'success': True})

    except (json.JSONDecodeError, InvalidOperation):
        return JsonResponse({'success': False, 'error': 'Invalid data format.'}, status=400)
    except Exception as e:
        logger.error(f"Error updating pricing for product {product_id}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

