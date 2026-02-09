# distributorplatform/app/product/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from tablib import Dataset
from decimal import Decimal, InvalidOperation

import datetime
import logging
import json
from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Q, Subquery, OuterRef, Sum, Prefetch
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage
from inventory.models import QuotationItem
from inventory.views import staff_required

from .models import Product, Category, CategoryGroup, ProductContentSection
from .forms import ProductUploadForm, ProductForm, CategoryForm
from .resources import ProductResource

from blog.models import Post
from blog.views import get_accessible_posts
from product.models import Product, Category, CategoryGroup, ProductContentSection, CategoryContentSection
from images.models import MediaImage, ImageCategory
from images.forms import ImageUploadForm
from order.views import agent_required
from images.models import MediaImage


logger = logging.getLogger(__name__)


def home(request):
    """
    Renders the new site home page with a sidebar layout.
    """
    # 1. Featured Products Logic (Unchanged)
    products_query = Product.objects.filter(is_featured=True).select_related('featured_image').order_by('-created_at')

    if request.user.is_authenticated and not request.user.is_anonymous:
        allowed_categories = Category.objects.filter(user_groups__users=request.user)
        products_query = products_query.filter(categories__in=allowed_categories).distinct()
    else:
        products_query = products_query.filter(members_only=False).distinct()

    featured_products = products_query[:6]

    # --- 2. SIDEBAR DATA (Unchanged) ---
    accessible_posts = get_accessible_posts(request.user).select_related('featured_image', 'author')

    announcements = accessible_posts.filter(
        post_type=Post.PostType.ANNOUNCEMENT
    ).order_by('-created_at')[:3]

    market_insights = accessible_posts.filter(
        post_type=Post.PostType.MARKET_INSIGHTS
    ).order_by('-created_at')[:5]

    latest_news_posts = accessible_posts.filter(
        post_type=Post.PostType.NEWS
    ).order_by('-created_at')[:4]

    # --- NEW: FAQ DATA ---
    faq_posts = accessible_posts.filter(
        post_type=Post.PostType.FAQ
    ).order_by('created_at')

    # 3. Categories Products Logic
    # FIX: Updated ordering to match Navigation Bar (display_order, name)
    categories_with_products = []
    if request.user.is_authenticated and not request.user.is_anonymous:
        cats_qs = Category.objects.filter(
            user_groups__users=request.user
        ).distinct().order_by('display_order', 'name') # <--- UPDATED
        product_prefetch = Prefetch(
            'products',
            queryset=Product.objects.select_related('featured_image').order_by('-created_at')
        )
        categories_with_products = cats_qs.prefetch_related(product_prefetch)
    else:
        cats_qs = Category.objects.filter(
            products__members_only=False
        ).distinct().order_by('display_order', 'name') # <--- UPDATED
        public_products_qs = Product.objects.filter(
            members_only=False
        ).select_related('featured_image').order_by('-created_at')
        categories_with_products = cats_qs.prefetch_related(
            Prefetch('products', queryset=public_products_qs)
        )

    context = {
        'featured_products': featured_products,
        'announcements': announcements,
        'sidebar_posts': market_insights,
        'latest_news_posts': latest_news_posts,
        'categories_with_products': categories_with_products,
        'faq_posts': faq_posts,
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



def product_list(request):
    """
    Product list with DEBUG logging to trace visibility issues.
    """
    selected_category_code = request.GET.get('category')
    search_query = request.GET.get('q')

    # --- 1. Product Filtering Logic ---
    products_query = None
    if request.user.is_authenticated and not request.user.is_anonymous:
        allowed_categories = Category.objects.filter(user_groups__users=request.user)
        products_query = Product.objects.filter(categories__in=allowed_categories).distinct()
    else:
        products_query = Product.objects.filter(members_only=False)

    # Apply Category filtering
    if selected_category_code:
        products_query = products_query.filter(categories__code=selected_category_code)

    # Apply Search Filtering
    if search_query:
        products_query = products_query.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Prefetch and Convert to List
    all_products = list(products_query.select_related('featured_image').distinct().order_by('name'))

    # --- SPLIT LOGIC ---
    promotional_products = [p for p in all_products if getattr(p, 'is_promotion', False)]
    regular_products = [p for p in all_products if not getattr(p, 'is_promotion', False)]

    # --- 2. Sidebar Data ---
    accessible_posts = get_accessible_posts(request.user).select_related('featured_image', 'author')
    announcements = accessible_posts.filter(post_type=Post.PostType.ANNOUNCEMENT).order_by('-created_at')[:3]
    sidebar_posts = accessible_posts.filter(featured_image__isnull=False, post_type=Post.PostType.NEWS).order_by('-created_at')[:5]

    product_upload_form = ProductUploadForm()
    category_obj = None
    if selected_category_code:
        category_obj = Category.objects.filter(code=selected_category_code).first()

    context = {
        'products': regular_products,
        'promotional_products': promotional_products,
        'product_upload_form': product_upload_form,
        'search_query': search_query,
        'announcements': announcements,
        'sidebar_posts': sidebar_posts,
        'selected_category_code': selected_category_code,
        'current_category': category_obj,
    }
    return render(request, 'product/product_list.html', context)

@staff_required
def api_manage_categories(request):
    """ API to list categories for the management table. """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    search = request.GET.get('search', '')
    page = request.GET.get('page', 1)

    # Updated ordering: Group > Display Order > Name
    queryset = Category.objects.select_related('group').order_by('group__name', 'display_order', 'name')

    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))

    paginator = Paginator(queryset, 50)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        return JsonResponse({'categories': [], 'pagination': {}})

    data = [{
        'id': cat.id,
        'name': cat.name,
        'code': cat.code,
        'group': cat.group.name,
        'display_order': cat.display_order, # --- NEW: Include display_order ---
        'description': cat.description or '',
        'page_title': cat.page_title or '',
        'edit_url': reverse('product:manage_category_edit', args=[cat.id])
    } for cat in page_obj.object_list]

    return JsonResponse({
        'categories': data,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })


@staff_required
def manage_category_edit(request, category_id):
    """
    Handle editing a category. Supports AJAX for Modal.
    """
    category = get_object_or_404(Category.objects.prefetch_related('content_sections'), pk=category_id)

    # --- AJAX GET: Fetch Data for Modal ---
    if request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        sections = list(category.content_sections.values('title', 'content').order_by('order'))
        data = {
            'id': category.id,
            'name': category.name,
            'page_title': category.page_title,
            'description': category.description,
            'display_order': category.display_order, # --- NEW ---
            'sections': sections,
            'update_url': reverse('product:manage_category_edit', args=[category.id])
        }
        return JsonResponse(data)

    # --- AJAX POST: Save Data from Modal ---
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                data = json.loads(request.body)
                form = CategoryForm(data, instance=category)
                if form.is_valid():
                    with transaction.atomic():
                        saved_cat = form.save()

                        # Handle Extra Sections
                        sections_data = data.get('sections', [])
                        saved_cat.content_sections.all().delete()

                        new_sections = []
                        for idx, section in enumerate(sections_data):
                            title = section.get('title', '').strip()
                            content = section.get('content', '').strip()
                            if title or content:
                                new_sections.append(CategoryContentSection(
                                    category=saved_cat,
                                    title=title,
                                    content=content,
                                    order=idx
                                ))
                        CategoryContentSection.objects.bulk_create(new_sections)

                    return JsonResponse({'success': True, 'message': f"Category '{saved_cat.name}' updated."})
                else:
                    return JsonResponse({'success': False, 'errors': form.errors}, status=400)
            except Exception as e:
                logger.error(f"Error saving category: {e}", exc_info=True)
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

    form = CategoryForm(instance=category)
    sections = list(category.content_sections.values('title', 'content').order_by('order'))
    context = {
        'form': form,
        'category': category,
        'title': f"Edit Category: {category.name}",
        'sections_json': sections,
        'is_subpage': True,
    }
    return render(request, 'product/manage_category_form.html', context)



@staff_required
def upload_products(request):
    """
    View for uploading product files.
    Processes POST requests from the modal on the product_list page.
    """
    logger.info("[upload_products] View called.")
    if request.method != 'POST':
        logger.warning("[upload_products] GET request received, redirecting.")
        return redirect(reverse('core:manage_dashboard') + '#products')

    redirect_url = reverse('core:manage_dashboard') + '#products'

    form = ProductUploadForm(request.POST, request.FILES)
    if form.is_valid():
        file = request.FILES['file']
        logger.info(f"[upload_products] Form is valid. Processing file: {file.name}")

        if not file.name.endswith(('.csv', '.xls', '.xlsx')):
            logger.warning(f"[upload_products] Invalid file format: {file.name}")
            messages.error(request, "Invalid file format. Please upload a .csv, .xls, or .xlsx file.")
            return redirect(redirect_url)

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
            return redirect(redirect_url)

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

        return redirect(redirect_url)

    logger.warning(f"[upload_products] Form was invalid. Errors: {form.errors.as_json()}")
    messages.error(request, "An error occurred with the upload form.")
    return redirect(redirect_url)


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
        return redirect(reverse('core:manage_dashboard') + '#products')

# --- START NEW VIEW ---
@staff_required
def manage_product_edit(request, product_id):
    """
    Handles fetching product data (GET) and updating product data (POST)
    via AJAX. Now supports extra content sections.
    """
    product = get_object_or_404(Product.objects.prefetch_related('featured_image', 'content_sections'), pk=product_id)

    if request.method == 'POST':
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
             messages.error(request, "Invalid request type.")
             return redirect('core:manage_dashboard')

        form = ProductForm(request.POST, request.FILES, instance=product)

        if form.is_valid():
            try:
                with transaction.atomic():
                    saved_product = form.save()

                    # --- Handle Extra Sections ---
                    sections_json = request.POST.get('sections_data')
                    if sections_json:
                        sections_data = json.loads(sections_json)

                        # Clear existing sections to replace them (simplest sync strategy)
                        # Alternatively, you could update by ID if preserving IDs matters.
                        saved_product.content_sections.all().delete()

                        new_sections = []
                        for idx, section in enumerate(sections_data):
                            title = section.get('title', '').strip()
                            content = section.get('content', '').strip()
                            if title and content:
                                new_sections.append(ProductContentSection(
                                    product=saved_product,
                                    title=title,
                                    content=content,
                                    order=idx
                                ))
                        ProductContentSection.objects.bulk_create(new_sections)

                logger.info(f"Product {product.sku} updated successfully via modal.")
                return JsonResponse({'success': True})
            except Exception as e:
                logger.error(f"Error saving product {product.sku}: {e}", exc_info=True)
                return JsonResponse({'success': False, 'errors': {'__all__': [str(e)]}}, status=500)
        else:
            logger.error(f"[SERVER] Product form is INVALID. Errors: {form.errors.as_json(escape_html=True)}")
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    elif request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Serialize sections
        sections = list(product.content_sections.values('title', 'content').order_by('order'))

        data = {
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'description_title': product.description_title,
            'description': product.description,
            'origin_country': product.origin_country, # --- NEW ---
            'sections': sections,
            'members_only': product.members_only,
            'is_featured': product.is_featured,
            'categories': list(product.categories.all().values_list('id', flat=True)),
            'suppliers': list(product.suppliers.all().values_list('id', flat=True)),
            'gallery_images': list(product.gallery_images.all().values_list('id', flat=True)),
            'featured_image': product.featured_image_id,
            'selectedImageUrl': product.featured_image.image.url if product.featured_image else '',
            'update_url': reverse('product:manage_product_edit', kwargs={'product_id': product.id})
        }
        return JsonResponse(data)

    messages.error(request, "Invalid request.")
    return redirect('core:manage_dashboard')


@staff_required
def api_manage_products(request):
    """
    API to fetch products for the management dashboard.
    Includes DEBUG logging for supplier cost calculation.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Filters ---
    search_query = request.GET.get('search', '')
    group_filter = request.GET.get('group', '')
    category_filter = request.GET.get('category', '')
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 50)

    # --- 2. Build Base Queryset ---
    queryset = Product.objects.annotate(
        # annotations if needed...
    ).select_related('featured_image').prefetch_related(
        Prefetch('categories', queryset=Category.objects.select_related('group')),
        'suppliers', # --- NEW: Prefetch suppliers ---
        Prefetch(
            'quotationitem_set',
            queryset=QuotationItem.objects.select_related('quotation', 'quotation__supplier')
                                          .prefetch_related('quotation__items')
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items'
        )
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
    paginator = Paginator(queryset, limit)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    # --- 5. Serialize ---
    serialized_products = []

    # [DEBUG] Start serialization loop
    logger.debug(f"[api_manage_products] Serializing {len(page_obj.object_list)} products...")

    for product in page_obj.object_list:
        category_list = [cat.name for cat in product.categories.all()]
        group_list = [cat.group.name for cat in product.categories.all() if cat.group]

        # --- NEW: Get Supplier List ---
        supplier_list = [s.name for s in product.suppliers.all()]

        # --- NEW: Extract latest cost per supplier ---
        supplier_costs = []
        seen_suppliers = set()

        if hasattr(product, 'latest_quotation_items'):
             # [DEBUG] Log found items for this product
             # logger.debug(f"[Product {product.sku}] Found {len(product.latest_quotation_items)} quotation items.")

             for item in product.latest_quotation_items:
                 sup_id = item.quotation.supplier_id
                 sup_name = item.quotation.supplier.name

                 if sup_id not in seen_suppliers:
                     seen_suppliers.add(sup_id)

                     cost = item.landed_cost_per_unit

                     # [DEBUG] Log calculated cost
                     # logger.debug(f"  -> Supplier: {sup_name}, Date: {item.quotation.date_quoted}, Cost: {cost}")

                     if cost is not None:
                         supplier_costs.append({
                             'supplier_name': sup_name or "Unknown",
                             'cost': cost, # Kept as Decimal for Encoder
                             'date': item.quotation.date_quoted # Kept as Date for Encoder
                         })
        else:
             logger.warning(f"[Product {product.sku}] 'latest_quotation_items' attribute missing.")

        # [DEBUG] Log final list for this product
        if len(supplier_costs) > 1:
            logger.info(f"[Product {product.sku}] Generated multiple supplier options: {supplier_costs}")
        # ---------------------------------------------

        product_data = {
            'id': product.pk,
            'sku': product.sku or '-',
            'name': product.name,
            'selling_price': product.selling_price,
            'is_promotion': product.is_promotion,
            'promotion_rate': product.promotion_rate,
            'profit_margin': product.profit_margin,
            'base_cost': product.base_cost,
            'supplier_costs': supplier_costs,
            'suppliers': supplier_list, # --- NEW: Included in response ---
            'category_groups': sorted(list(set(group_list))),
            'categories': sorted(list(set(category_list))),
            'featured_image_url': product.featured_image.image.url if product.featured_image else None,
            'featured_image_alt': product.featured_image.alt_text if product.featured_image else product.name,
            'featured_image_id': product.featured_image_id,
            'featured_image_title': product.featured_image.title if product.featured_image else None,
            'gallery_image_ids': list(product.gallery_images.all().values_list('id', flat=True))
        }
        serialized_products.append(product_data)

    # --- 6. Return JSON with Encoder ---
    # FIXED: Added DjangoJSONEncoder to handle Decimal and Date objects
    return JsonResponse({
        'items': serialized_products,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    }, encoder=DjangoJSONEncoder)



@staff_required
def api_manage_pricing(request, product_id):
    """
    Handles updating pricing with DEBUG logging to trace data saving issues.
    """
    if not (request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    product = get_object_or_404(Product, pk=product_id)

    try:
        # [DEBUG] Log the raw incoming data
        data = json.loads(request.body)
        promotion_rate_str = data.get('promotion_rate')

        selling_price_str = data.get('selling_price')
        profit_margin_str = data.get('profit_margin')

        # [DEBUG] Check if 'is_promotion' is in the payload
        if 'is_promotion' in data:
            new_promo_status = bool(data['is_promotion'])
            logger.info(f"[DEBUG][Pricing] Payload contains 'is_promotion': {new_promo_status}. Current DB value: {product.is_promotion}")
            product.is_promotion = new_promo_status
        else:
            logger.warning(f"[DEBUG][Pricing] 'is_promotion' key MISSING from payload. Flag will not change.")

        product.selling_price = Decimal(selling_price_str) if selling_price_str is not None else None
        product.profit_margin = Decimal(profit_margin_str) if profit_margin_str is not None else None
        product.promotion_rate = Decimal(promotion_rate_str) if promotion_rate_str is not None else None

        # [DEBUG] Log the fields intended for update
        update_fields_list = ['selling_price', 'profit_margin', 'is_promotion']
        logger.info(f"[DEBUG][Pricing] Attempting to save with update_fields: {update_fields_list}")

        # --- CRITICAL: Ensure 'is_promotion' is in this list ---
        product.save(update_fields=['selling_price', 'profit_margin', 'is_promotion', 'promotion_rate'])

        # [DEBUG] Verify the save by reloading from DB
        product.refresh_from_db()
        logger.info(f"[DEBUG][Pricing] Post-Save Check -> is_promotion: {product.is_promotion}")

        return JsonResponse({'success': True})

    except (json.JSONDecodeError, InvalidOperation) as e:
        logger.error(f"[DEBUG][Pricing] JSON/Decimal Error: {e}")
        return JsonResponse({'success': False, 'error': 'Invalid data format.'}, status=400)
    except Exception as e:
        logger.error(f"[DEBUG][Pricing] Critical Error: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def api_get_product_details(request, sku):
    """
    API endpoint for the product quick view modal.
    Returns detailed product info.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        product = Product.objects.prefetch_related(
            'gallery_images',
            Prefetch(
                'quotationitem_set',
                queryset=QuotationItem.objects.select_related('quotation')
                                              .prefetch_related('quotation__items')
                                              .order_by('-quotation__date_quoted'),
                to_attr='latest_quotation_items'
            )
        ).select_related('featured_image').get(sku=sku)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    # --- MODIFIED LOGIC ---

    # 1. Basic Info (Visible to everyone)
    selling_price = product.selling_price

    # 2. Default Sensitive Data (Hidden)
    base_cost = None
    profit = None
    agent_commission = None
    is_orderable = False
    user_role = 'guest' # guest, customer, agent

    # 3. User-Specific Logic
    if request.user.is_authenticated:
        # User is logged in (Customer or Agent)

        # Check for Agent status (Commission > 0)
        agent_group = request.user.user_groups.filter(commission_percentage__gt=0).first()

        if agent_group:
            user_role = 'agent'
            # Agents see cost/profit/commission
            base_cost = product.base_cost
            if base_cost is not None and selling_price is not None:
                profit = selling_price - base_cost
                if profit > 0:
                    is_orderable = True
                    commission_rate = agent_group.commission_percentage / Decimal('100.00')
                    agent_commission = profit * commission_rate
        else:
            user_role = 'customer'
            # Customers just need a selling price to order
            if selling_price is not None:
                is_orderable = True

    else:
        # Guest: Sees price, but cannot order
        pass

    # Serialize gallery
    gallery = [
        {'id': img.id, 'url': img.image.url, 'alt_text': img.alt_text}
        for img in product.gallery_images.all()
    ]

    data = {
        'id': product.id,
        'name': product.name,
        'sku': product.sku,
        'description': product.description,
        'origin_country': product.origin_country,
        'featured_image_url': product.featured_image.image.url if product.featured_image else None,
        'gallery_images': gallery,
        'selling_price': selling_price,
        'is_promotion': product.is_promotion,
        'promotion_rate': product.promotion_rate,
        'discounted_price': product.discounted_price,
        # Logic flags
        'is_orderable': is_orderable,
        'user_role': user_role,
        'is_authenticated': request.user.is_authenticated,

        # Sensitive Data (Null for guests/customers)
        'base_cost': base_cost,
        'profit': profit,
        'agent_commission': agent_commission,
    }

    return JsonResponse(data)


def product_detail(request, sku):
    """
    Public page showing a single product.
    Now includes sidebar data AND agent specific calculations.
    """
    # Find the product by its SKU
    product = get_object_or_404(Product.objects.prefetch_related('gallery_images', 'featured_image'), sku=sku)

    # Members-only check
    if product.members_only and not request.user.is_authenticated:
        messages.error(request, "This is a members-only product. Please log in to view.")
        return redirect('user:login')

    # --- SIDEBAR DATA ---
    accessible_posts = get_accessible_posts(request.user).select_related('featured_image', 'author')

    # 1. Announcements (Top priority)
    announcements = accessible_posts.filter(
        post_type=Post.PostType.ANNOUNCEMENT
    ).order_by('-created_at')[:3]

    # 2. Latest News (Standard posts)
    sidebar_posts = accessible_posts.filter(
        featured_image__isnull=False,
        post_type=Post.PostType.NEWS
    ).order_by('-created_at')[:5]

    # --- AGENT LOGIC ---
    is_agent = False
    agent_estimated_profit = None

    if request.user.is_authenticated:
        agent_group = request.user.user_groups.filter(commission_percentage__gt=0).first()
        if agent_group:
            is_agent = True
            # Calculate potential commission
            if product.selling_price is not None and product.base_cost is not None:
                profit = product.selling_price - product.base_cost
                if profit > 0:
                    commission_rate = agent_group.commission_percentage / Decimal('100.00')
                    agent_estimated_profit = profit * commission_rate

    context = {
        'product': product,
        'announcements': announcements,
        'sidebar_posts': sidebar_posts,
        'is_agent': is_agent,
        'agent_estimated_profit': agent_estimated_profit,
    }
    return render(request, 'product/product_detail.html', context)


@staff_required
def manage_category_create(request):
    """
    Handles creating a new category via AJAX (Modal).
    """
    if request.method == 'POST':
        # Check for AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                data = json.loads(request.body)
                form = CategoryForm(data)

                if form.is_valid():
                    with transaction.atomic():
                        saved_cat = form.save()

                        # Handle Extra Sections
                        sections_data = data.get('sections', [])
                        if sections_data:
                            new_sections = []
                            for idx, section in enumerate(sections_data):
                                title = section.get('title', '').strip()
                                content = section.get('content', '').strip()
                                if title or content:
                                    new_sections.append(CategoryContentSection(
                                        category=saved_cat,
                                        title=title,
                                        content=content,
                                        order=idx
                                    ))
                            CategoryContentSection.objects.bulk_create(new_sections)

                    return JsonResponse({'success': True, 'message': "Category created successfully."})
                else:
                    return JsonResponse({'success': False, 'errors': form.errors}, status=400)
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

# --- UPDATE THIS EXISTING VIEW ---
@staff_required
def manage_category_edit(request, category_id):
    """
    Handle editing a category. Supports AJAX for Modal.
    """
    category = get_object_or_404(Category.objects.prefetch_related('content_sections'), pk=category_id)

    # --- AJAX GET: Fetch Data for Modal ---
    if request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        sections = list(category.content_sections.values('title', 'content').order_by('order'))
        data = {
            'id': category.id,
            'name': category.name,
            'page_title': category.page_title,
            'description': category.description,
            'sections': sections,
            'update_url': reverse('product:manage_category_edit', args=[category.id])
        }
        return JsonResponse(data)

    # --- AJAX POST: Save Data from Modal ---
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                data = json.loads(request.body)
                form = CategoryForm(data, instance=category)
                if form.is_valid():
                    with transaction.atomic():
                        saved_cat = form.save()

                        # Handle Extra Sections
                        sections_data = data.get('sections', [])
                        # Clear existing sections to replace/sync
                        saved_cat.content_sections.all().delete()

                        new_sections = []
                        for idx, section in enumerate(sections_data):
                            title = section.get('title', '').strip()
                            content = section.get('content', '').strip()
                            if title or content:
                                new_sections.append(CategoryContentSection(
                                    category=saved_cat,
                                    title=title,
                                    content=content,
                                    order=idx
                                ))
                        CategoryContentSection.objects.bulk_create(new_sections)

                    return JsonResponse({'success': True, 'message': f"Category '{saved_cat.name}' updated."})
                else:
                    return JsonResponse({'success': False, 'errors': form.errors}, status=400)
            except Exception as e:
                logger.error(f"Error saving category: {e}", exc_info=True)
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # ... (Keep existing Standard POST logic if you want fallback, or remove it) ...
        # For brevity, I'm omitting the fallback standard POST as the modal replaces it.

    # ... (Keep existing Standard GET for standalone page if needed, otherwise this can be removed)
    form = CategoryForm(instance=category)
    sections = list(category.content_sections.values('title', 'content').order_by('order'))
    context = {
        'form': form,
        'category': category,
        'title': f"Edit Category: {category.name}",
        'sections_json': sections,
        'is_subpage': True,
    }
    return render(request, 'product/manage_category_form.html', context)
