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
import os
import re
import tempfile
from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Q, Subquery, OuterRef, Sum, Prefetch
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator, EmptyPage
from inventory.models import QuotationItem, InventoryBatch
from inventory.views import staff_required

from .models import Product, Category, CategoryGroup, ProductContentSection, IgnoredMergeSuggestion, ProductPriceTier
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

    all_products = list(products_query.select_related('featured_image').distinct().order_by('display_order', 'name'))

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
    AJAX-only, two-step product upload:
    1) Preview (dry_run) with temp file and first 10 rows.
    2) Confirm import using stored temp file path.
    """
    if request.method != 'POST' or request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        confirm_flag = request.POST.get('confirm', 'false').lower() == 'true'
        product_resource = ProductResource()

        # --- Phase 2: Confirm & Import ---
        if confirm_flag:
            temp_file_path = request.POST.get('temp_file_path')
            if not temp_file_path:
                return JsonResponse({'success': False, 'error': 'Missing temp_file_path.'}, status=400)

            if not os.path.exists(temp_file_path):
                return JsonResponse({'success': False, 'error': 'Temporary file not found. Please re-upload.'}, status=400)

            try:
                dataset = Dataset()
                # Determine format based on extension
                if temp_file_path.endswith('.csv'):
                    with open(temp_file_path, 'rb') as f:
                        file_content = f.read()
                    try:
                        decoded_content = file_content.decode('utf-8')
                    except UnicodeDecodeError:
                        logger.warning("[upload_products] UTF-8 decode failed for temp CSV, falling back to latin-1.")
                        decoded_content = file_content.decode('latin-1')
                    dataset.load(decoded_content, format='csv')
                else:
                    with open(temp_file_path, 'rb') as f:
                        dataset.load(f.read(), format='xlsx')

                logger.info(f"[upload_products] Loaded dataset from temp file for final import: {temp_file_path}")

                with transaction.atomic():
                    result = product_resource.import_data(dataset, dry_run=False, use_transactions=True)

                os.remove(temp_file_path)
                logger.info("[upload_products] Final import successful, temp file removed.")

                if result.has_errors() or result.has_validation_errors():
                    logger.warning("[upload_products] Final import reported errors after dry-run success.")
                return JsonResponse({'success': True, 'message': 'Imported successfully!'})

            except Exception as e:
                logger.error(f"[upload_products] Error during confirm import: {e}", exc_info=True)
                # Best-effort cleanup
                try:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                except Exception:
                    pass
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        # --- Phase 1: Preview / Dry Run ---
        upload_file = request.FILES.get('file')
        if upload_file is None:
            return JsonResponse({'success': False, 'error': 'No file uploaded.'}, status=400)

        filename = upload_file.name
        logger.info(f"[upload_products] Preview requested for file: {filename}")

        if not filename.endswith(('.csv', '.xls', '.xlsx')):
            return JsonResponse({'success': False, 'error': 'Invalid file format. Please upload a .csv, .xls, or .xlsx file.'}, status=400)

        # Save to a secure temporary file
        try:
            suffix = os.path.splitext(filename)[1] or ''
            fd, temp_path = tempfile.mkstemp(prefix='product_upload_', suffix=suffix)
            with os.fdopen(fd, 'wb') as tmp:
                for chunk in upload_file.chunks():
                    tmp.write(chunk)
            logger.info(f"[upload_products] Temp file created at: {temp_path}")
        except Exception as e:
            logger.error(f"[upload_products] Failed to create temp file: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': 'Could not save uploaded file for processing.'}, status=500)

        try:
            dataset = Dataset()
            if filename.endswith('.csv'):
                with open(temp_path, 'rb') as f:
                    file_content = f.read()
                try:
                    decoded_content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    logger.warning("[upload_products] UTF-8 decode failed for CSV, falling back to latin-1.")
                    decoded_content = file_content.decode('latin-1')
                dataset.load(decoded_content, format='csv')
            else:
                with open(temp_path, 'rb') as f:
                    dataset.load(f.read(), format='xlsx')
            logger.info("[upload_products] Dataset loaded from temp file for preview.")
        except Exception as e:
            logger.error(f"[upload_products] Error reading temp file into dataset: {e}", exc_info=True)
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return JsonResponse({'success': False, 'error': f'Error reading file: {e}'}, status=500)

        # Perform dry run
        try:
            result = product_resource.import_data(dataset, dry_run=True, use_transactions=True)
        except Exception as e:
            logger.error(f"[upload_products] Error during dry run import: {e}", exc_info=True)
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return JsonResponse({'success': False, 'error': f'Error validating file: {e}'}, status=500)

        # Check for hard errors first
        if result.has_errors():
            try:
                os.remove(temp_path)
            except Exception:
                pass
            errors = []
            try:
                for err in result.row_errors():
                    row_num, row_errors_list = err[0], err[1]
                    if row_errors_list:
                        first_err = row_errors_list[0]
                        err_msg = getattr(first_err, 'error', str(first_err))
                    else:
                        err_msg = "Unknown error"
                    errors.append(f"Row {row_num}: {err_msg}")
            except Exception as e:
                errors.append(str(e))
            return JsonResponse({
                'success': False,
                'error': "Import errors found.",
                'details': errors
            }, status=400)

        # Build dataset row dicts once for fallback (same order as result.rows)
        headers = list(dataset.headers) if dataset.headers else []
        dataset_row_dicts = [dict(zip(headers, row)) for row in dataset]

        # Safely generate preview data
        preview_rows = []
        valid_rows_count = 0

        for idx, row_result in enumerate(result.rows):
            itype = getattr(row_result, 'import_type', None)
            if itype is None or str(itype).lower() not in ('new', 'update'):
                continue
            valid_rows_count += 1

            final_sku = None
            final_name = None

            # 1. Primary: generated model instance (django-import-export may use .instance or .object)
            for attr in ('instance', 'object'):
                obj = getattr(row_result, attr, None)
                if obj is not None:
                    final_sku = getattr(obj, 'sku', None)
                    final_name = getattr(obj, 'name', None)
                    if final_sku or final_name:
                        break

            # 2. Fallback: raw row dict (raw_values / row_values; may be dict or OrderedDict)
            if not final_sku or not final_name:
                raw_dict = getattr(row_result, 'raw_values', None) or getattr(row_result, 'row_values', None)
                if raw_dict is not None and not isinstance(raw_dict, dict):
                    raw_dict = dict(raw_dict) if hasattr(raw_dict, 'items') else {}
                elif raw_dict is None:
                    raw_dict = {}
                final_sku = final_sku or (raw_dict.get('sku') if raw_dict else None)
                final_name = final_name or (raw_dict.get('name') if raw_dict else None)

            # 3. Fallback: same row from the dataset we imported (name + recompute SKU to match before_import_row)
            if (not final_sku or not final_name) and idx < len(dataset_row_dicts):
                row_dict = dataset_row_dicts[idx]
                final_name = final_name or row_dict.get('name') or 'Unknown'
                final_sku = final_sku or ProductResource.get_effective_sku_for_row(row_dict) or 'N/A'

            final_sku = final_sku or 'N/A'
            final_name = final_name or 'Unknown'

            preview_rows.append({
                'status': str(itype).upper() if itype is not None else 'NEW',
                'name': final_name,
                'generated_sku': final_sku,
            })

        # Check if valid_rows_count is 0 but we have validation errors
        if valid_rows_count == 0 and result.has_validation_errors():
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return JsonResponse({
                'success': False,
                'error': "All rows failed validation.",
                'details': ["Check file formatting."]
            }, status=400)

        return JsonResponse({
            'success': True,
            'require_confirmation': True,
            'temp_file_path': temp_path,
            'total_rows': valid_rows_count,
            'preview_data': preview_rows[:15],
        })

    except Exception as e:
        logger.error(f"[upload_products] Unexpected error: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_required
def scrape_website_products(request):
    """
    Deprecated: website scraping has been disabled and this endpoint is no longer in use.
    Kept only as a stub so old imports/references fail gracefully if encountered.
    """
    return JsonResponse(
        {'success': False, 'error': 'Website scraping has been disabled.'},
        status=400,
    )

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
    Handles fetching product data (GET) and updating product data (POST) via AJAX.
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
                    sections_json = request.POST.get('sections_data')
                    if sections_json:
                        sections_data = json.loads(sections_json)
                        saved_product.content_sections.all().delete()
                        new_sections = []
                        for idx, section in enumerate(sections_data):
                            title = section.get('title', '').strip()
                            content = section.get('content', '').strip()
                            if title and content:
                                new_sections.append(ProductContentSection(
                                    product=saved_product, title=title, content=content, order=idx
                                ))
                        ProductContentSection.objects.bulk_create(new_sections)
                return JsonResponse({'success': True})
            except Exception as e:
                logger.error(f"Error saving product {product.sku}: {e}", exc_info=True)
                return JsonResponse({'success': False, 'errors': {'__all__': [str(e)]}}, status=500)
        else:
            return JsonResponse({'success': False, 'errors': json.loads(form.errors.as_json())}, status=400)

    elif request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        sections = list(product.content_sections.values('title', 'content').order_by('order'))
        data = {
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'description_title': product.description_title,
            'description': product.description,
            'origin_country': product.origin_country,
            'sections': sections,
            'members_only': product.members_only,
            'is_featured': product.is_featured,
            'is_best_seller': product.is_best_seller, # --- NEW: Return Best Seller Status ---
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
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    search_query = request.GET.get('search', '')
    group_filter = request.GET.get('group', '')
    category_filter = request.GET.get('category', '')
    page_number = request.GET.get('page', 1)
    limit = request.GET.get('limit', 50)

    queryset = Product.objects.select_related('featured_image').prefetch_related(
        Prefetch('categories', queryset=Category.objects.select_related('group')),
        'suppliers',
        Prefetch(
            'quotationitem_set',
            queryset=QuotationItem.objects.select_related('quotation', 'quotation__supplier')
                                          .prefetch_related('quotation__items')
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items'
        )
    ).order_by('name')

    if search_query:
        queryset = queryset.filter(Q(name__icontains=search_query) | Q(sku__icontains=search_query))
    if group_filter:
        queryset = queryset.filter(categories__group__name=group_filter)
    if category_filter:
        queryset = queryset.filter(categories__name=category_filter)

    queryset = queryset.distinct()
    paginator = Paginator(queryset, limit)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    serialized_products = []
    for product in page_obj.object_list:
        category_list = [cat.name for cat in product.categories.all()]
        group_list = [cat.group.name for cat in product.categories.all() if cat.group]

        # Direct M2M suppliers attached to the product
        m2m_supplier_list = [s.name for s in product.suppliers.all()]
        supplier_costs: list[dict] = []
        seen_suppliers = set()

        # When available, use the prefetched latest_quotation_items for performance.
        # If not present (or empty), fall back to a direct query so that merged
        # products still see ALL quotation items and supplier pricing.
        if hasattr(product, "latest_quotation_items") and product.latest_quotation_items:
            quotation_items = product.latest_quotation_items
        else:
            quotation_items = (
                QuotationItem.objects.filter(product=product)
                .select_related("quotation", "quotation__supplier")
                .prefetch_related("quotation__items")
                .order_by("-quotation__date_quoted")
            )

        for item in quotation_items:
            sup_id = item.quotation.supplier_id
            if sup_id in seen_suppliers:
                continue
            seen_suppliers.add(sup_id)
            cost = item.landed_cost_per_unit
            if cost is not None:
                supplier_costs.append(
                    {
                        "supplier_name": item.quotation.supplier.name or "Unknown",
                        "cost": cost,
                        "date": item.quotation.date_quoted,
                    }
                )

        # For the "Suppliers" column in Manage Products, we want to reflect all
        # suppliers that currently have pricing for this product, not just those
        # explicitly attached via the M2M field. If there are supplier_costs,
        # derive the display list from them; otherwise fall back to the M2M list.
        if supplier_costs:
            suppliers_display = sorted({sc["supplier_name"] for sc in supplier_costs})
        else:
            suppliers_display = m2m_supplier_list

        # DEBUG: inspect pricing and supplier costs for each product row in Manage Products
        logger.debug(
            "[manage_products] product_id=%s sku=%s saved_base_cost=%s base_cost_prop=%s supplier_costs=%s",
            product.pk,
            product.sku,
            getattr(product, "saved_base_cost", None),
            product.base_cost,
            [(sc["supplier_name"], sc["cost"], sc["date"]) for sc in supplier_costs],
        )

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
            'suppliers': suppliers_display,
            'category_groups': sorted(list(set(group_list))),
            'categories': sorted(list(set(category_list))),
            'featured_image_url': product.featured_image.image.url if product.featured_image else None,
            'featured_image_alt': product.featured_image.alt_text if product.featured_image else product.name,
            'featured_image_id': product.featured_image_id,
            'featured_image_title': product.featured_image.title if product.featured_image else None,
            'gallery_image_ids': list(product.gallery_images.all().values_list('id', flat=True)),
            'is_best_seller': product.is_best_seller, # --- NEW: Included in API response ---
        }
        serialized_products.append(product_data)

    return JsonResponse({
        'items': serialized_products,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    }, encoder=DjangoJSONEncoder)



def _normalize_product_name_for_fuzzy(value):
    """
    Helper for cleaning product names before fuzzy comparison.
    - Use only part before '|' (English name)
    - Strip special characters
    - Lowercase and collapse whitespace
    """
    if not value:
        return "", []
    base = str(value).split("|", 1)[0]
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", base).lower()
    tokens = [t for t in cleaned.split() if t]
    return " ".join(tokens), tokens


def _name_similarity(tokens_a, tokens_b):
    """Simple token-overlap similarity between two token lists."""
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    overlap = len(set_a & set_b)
    return (2.0 * overlap) / (len(set_a) + len(set_b))


@staff_required
def api_product_merge_suggestions(request):
    """
    Returns groups of products whose names look similar, to help with cleaning.
    Uses a lightweight token-overlap fuzzy match on a limited subset.
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"error": "Invalid request"}, status=400)

    search_query = request.GET.get("search", "").strip()
    try:
        min_score = float(request.GET.get("min_score", "0.7"))
    except ValueError:
        min_score = 0.7
    try:
        limit = int(request.GET.get("limit", "200"))
    except ValueError:
        limit = 200

    qs = Product.objects.prefetch_related("suppliers").only("id", "name", "sku", "selling_price")
    if search_query:
        qs = qs.filter(Q(name__icontains=search_query) | Q(sku__icontains=search_query))
    products = list(qs.order_by("name")[:limit])

    # Pre-compute tokens
    norm_tokens = {}
    for p in products:
        _, tokens = _normalize_product_name_for_fuzzy(p.name)
        norm_tokens[p.id] = tokens

    # Build similarity graph (adjacency list)
    n = len(products)
    adjacency = {p.id: set() for p in products}
    for i in range(n):
        pi = products[i]
        ti = norm_tokens.get(pi.id) or []
        if not ti:
            continue
        for j in range(i + 1, n):
            pj = products[j]
            tj = norm_tokens.get(pj.id) or []
            if not tj:
                continue
            score = _name_similarity(ti, tj)
            if score >= min_score:
                adjacency[pi.id].add(pj.id)
                adjacency[pj.id].add(pi.id)

    # Find connected components (each is a merge candidate group)
    visited = set()
    groups = []
    for p in products:
        if p.id in visited:
            continue
        stack = [p.id]
        component_ids = []
        while stack:
            pid = stack.pop()
            if pid in visited:
                continue
            visited.add(pid)
            component_ids.append(pid)
            stack.extend(adjacency.get(pid, []))
        if len(component_ids) >= 2:
            component_products = [pp for pp in products if pp.id in component_ids]
            component_products.sort(key=lambda x: x.name.lower())
            groups.append({
                "group_id": min(component_ids),
                "products": [
                    {
                        "id": x.id,
                        "sku": x.sku or "",
                        "name": x.name,
                        "selling_price": str(x.selling_price) if x.selling_price is not None else None,
                        "suppliers": [s.name for s in x.suppliers.all()],
                    }
                    for x in component_products
                ],
            })

    # Exclude groups that exactly match a previously dismissed combination (Duplicate Checklist memory)
    ignored_signatures = set(
        IgnoredMergeSuggestion.objects.values_list("product_ids_signature", flat=True)
    )
    filtered_groups = []
    for g in groups:
        ids = sorted(p["id"] for p in g["products"])
        signature = ",".join(str(i) for i in ids)
        if signature not in ignored_signatures:
            filtered_groups.append(g)

    return JsonResponse({"groups": filtered_groups})


@staff_required
def api_merge_products(request):
    """
    Merge secondary products into a primary product.
    POST JSON: { \"primary_id\": int, \"merge_ids\": [int, ...] }

    Moves key references (QuotationItem, InventoryBatch, OrderItem, ProductContentSection),
    merges categories/suppliers/gallery_images, then deletes the merged products.
    """
    if not (request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest"):
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)

    try:
        payload = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

    primary_id = payload.get("primary_id")
    merge_ids = payload.get("merge_ids") or []
    if not primary_id or not merge_ids:
        return JsonResponse({"success": False, "error": "primary_id and merge_ids are required."}, status=400)

    merge_ids = [int(i) for i in merge_ids if int(i) != int(primary_id)]
    if not merge_ids:
        return JsonResponse({"success": False, "error": "No valid secondary product IDs to merge."}, status=400)

    primary = get_object_or_404(Product, pk=primary_id)
    secondaries = list(Product.objects.filter(pk__in=merge_ids))
    if not secondaries:
        return JsonResponse({"success": False, "error": "No matching secondary products found."}, status=404)

    from order.models import OrderItem
    from product.models import ProductContentSection

    try:
        with transaction.atomic():
            # 1) Merge many-to-many relations on the primary (categories, suppliers, gallery)
            for s in secondaries:
                primary.categories.add(*s.categories.all())
                primary.suppliers.add(*s.suppliers.all())
                primary.gallery_images.add(*s.gallery_images.all())

            # 2) Transfer all Supplier Quotations (QuotationItem) and other FKs to the master.
            #    Master keeps its SKU and Name; merged products' quotation/cost data is retained on primary.
            QuotationItem.objects.filter(product__in=secondaries).update(product=primary)
            InventoryBatch.objects.filter(product__in=secondaries).update(product=primary)
            OrderItem.objects.filter(product__in=secondaries).update(product=primary)
            ProductContentSection.objects.filter(product__in=secondaries).update(product=primary)

            # 3) Delete secondary products (their SKUs/names disappear from the active catalog)
            Product.objects.filter(pk__in=[s.id for s in secondaries]).delete()

    except Exception as e:
        logger.exception("Error while merging products")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": True, "merged_count": len(secondaries)})


@staff_required
def api_ignore_merge_suggestion(request):
    """
    POST JSON: { "product_ids": [1, 2, 3] }.
    Stores this combination as a dismissed "Not duplicates" group so it won't appear again.
    If the same set is suggested later (e.g. after a new product joins the group), the new set
    has a different signature and will reappear.
    """
    if not (request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest"):
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)
    try:
        payload = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)
    product_ids = payload.get("product_ids") or []
    if not product_ids:
        return JsonResponse({"success": False, "error": "product_ids is required."}, status=400)
    try:
        ids = sorted(int(i) for i in product_ids)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "product_ids must be a list of integers."}, status=400)
    signature = ",".join(str(i) for i in ids)
    if len(signature) > 500:
        return JsonResponse({"success": False, "error": "Too many product IDs."}, status=400)
    IgnoredMergeSuggestion.objects.get_or_create(
        product_ids_signature=signature,
        defaults={},
    )
    return JsonResponse({"success": True})


@staff_required
def api_product_search(request):
    """
    GET ?search=...&limit=50. Returns products matching name or SKU (for Duplicate Checklist custom group).
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"error": "Invalid request"}, status=400)
    search_query = request.GET.get("search", "").strip()
    try:
        limit = min(int(request.GET.get("limit", "50")), 100)
    except ValueError:
        limit = 50
    qs = Product.objects.all().only("id", "name", "sku", "selling_price")
    if search_query:
        qs = qs.filter(Q(name__icontains=search_query) | Q(sku__icontains=search_query))
    products = list(qs.order_by("name")[:limit])
    return JsonResponse({
        "products": [
            {
                "id": p.id,
                "sku": p.sku or "",
                "name": p.name,
                "selling_price": str(p.selling_price) if p.selling_price is not None else None,
            }
            for p in products
        ]
    })


@staff_required
def api_manage_pricing(request, product_id):
    """
    Handles updating pricing with DEBUG logging to trace data saving issues.
    """
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    product = get_object_or_404(Product, pk=product_id)

    # --- GET: return fresh pricing data for the modal (avoids frontend caching issues) ---
    if request.method == 'GET':
        # Recompute supplier_costs exactly like manage-products does, so the modal
        # always uses a fresh, server-side view of quotations.
        supplier_costs: list[dict] = []
        seen_suppliers = set()

        if hasattr(product, "latest_quotation_items") and product.latest_quotation_items:
            quotation_items = product.latest_quotation_items
        else:
            quotation_items = (
                QuotationItem.objects.filter(product=product)
                .select_related("quotation", "quotation__supplier")
                .prefetch_related("quotation__items")
                .order_by("-quotation__date_quoted")
            )

        for item in quotation_items:
            sup_id = item.quotation.supplier_id
            if sup_id in seen_suppliers:
                continue
            seen_suppliers.add(sup_id)
            cost = item.landed_cost_per_unit
            if cost is not None:
                supplier_costs.append(
                    {
                        "supplier_name": item.quotation.supplier.name or "Unknown",
                        "cost": cost,
                        "date": item.quotation.date_quoted,
                    }
                )

        base_cost = product.base_cost
        # Price tiers: return min_quantity, price, and computed profit_margin for modal editing
        price_tiers_data = []
        for tier in product.price_tiers.order_by('-min_quantity'):
            margin = None
            if base_cost is not None and tier.price and tier.price > 0:
                margin = round(float((tier.price - base_cost) / tier.price * 100), 1)
            price_tiers_data.append({
                'min_quantity': tier.min_quantity,
                'price': str(tier.price),
                'profit_margin': margin if margin is not None else None,
            })

        return JsonResponse({
            'success': True,
            'id': product.pk,
            'sku': product.sku,
            'name': product.name,
            'selling_price': str(product.selling_price) if product.selling_price is not None else None,
            'profit_margin': str(product.profit_margin) if product.profit_margin is not None else None,
            'is_promotion': product.is_promotion,
            'promotion_rate': str(product.promotion_rate) if product.promotion_rate is not None else None,
            'saved_base_cost': str(product.saved_base_cost) if getattr(product, "saved_base_cost", None) is not None else None,
            'base_cost': str(base_cost) if base_cost is not None else None,
            'supplier_costs': supplier_costs,
            'price_tiers': price_tiers_data,
        })

    # --- POST: existing pricing update flow ---
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

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
        base_cost_str = data.get('base_cost')
        product.saved_base_cost = Decimal(base_cost_str) if base_cost_str is not None and base_cost_str != '' else None

        # [DEBUG] Log the fields intended for update
        update_fields_list = ['selling_price', 'profit_margin', 'is_promotion', 'saved_base_cost']
        logger.info(f"[DEBUG][Pricing] Attempting to save with update_fields: {update_fields_list}")

        # --- CRITICAL: Ensure 'is_promotion' is in this list ---
        product.save(update_fields=['selling_price', 'profit_margin', 'is_promotion', 'promotion_rate', 'saved_base_cost'])

        # --- Price tiers: replace all tiers with payload ---
        # Price is the source of truth; profit_margin (if provided) is for backward compatibility.
        base_cost = product.saved_base_cost if product.saved_base_cost is not None else product.base_cost
        tiers_payload = data.get('price_tiers') or []
        ProductPriceTier.objects.filter(product=product).delete()
        for row in tiers_payload:
            try:
                min_qty = int(row.get('min_quantity', 0))
                if min_qty < 1:
                    continue
                price_val = row.get('price')

                price = None
                # 1) Prefer explicit price from payload
                if price_val not in (None, ''):
                    price = Decimal(str(price_val))
                else:
                    # 2) Fallback: compute from profit_margin (legacy behaviour)
                    margin_val = row.get('profit_margin')
                    if margin_val is None or margin_val == '':
                        continue
                    if base_cost is None or base_cost <= 0:
                        continue
                    margin = Decimal(str(margin_val))
                    if margin >= 100:
                        continue
                    # selling_price = base_cost / (1 - margin/100)
                    price = base_cost / (1 - margin / Decimal('100'))

                if price is None or price <= 0:
                    continue

                ProductPriceTier.objects.create(product=product, min_quantity=min_qty, price=price)
            except (ValueError, TypeError, InvalidOperation):
                continue

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

@staff_required
def export_products_pdf(request):
    """
    Renders selected products in a clean, print-friendly Grid layout grouped by Category.
    """
    ids = request.GET.get('ids', '')
    if not ids:
        messages.error(request, "No products selected.")
        return redirect(reverse('core:manage_dashboard') + '#products')

    try:
        id_list = [int(i) for i in ids.split(',') if i.strip().isdigit()]
    except ValueError:
        id_list = []

    if not id_list:
        messages.error(request, "Invalid selection.")
        return redirect(reverse('core:manage_dashboard') + '#products')

    # Fetch products with related data (including price_tiers for PDF)
    products = Product.objects.filter(id__in=id_list)\
        .select_related('featured_image')\
        .prefetch_related('categories', 'price_tiers')\
        .order_by('name')

    # Group products by their first/primary category
    grouped_products = {}

    for product in products:
        cats = product.categories.all()
        # Use the first category found as the grouping key, or "Uncategorized"
        primary_cat = cats[0].name if cats else "Uncategorized"

        if primary_cat not in grouped_products:
            grouped_products[primary_cat] = []
        grouped_products[primary_cat].append(product)

    # Sort categories alphabetically, ensuring "Uncategorized" is last
    sorted_keys = sorted(grouped_products.keys())
    if "Uncategorized" in sorted_keys:
        sorted_keys.remove("Uncategorized")
        sorted_keys.append("Uncategorized")

    # Create a sorted dictionary
    sorted_grouped_products = {key: grouped_products[key] for key in sorted_keys}

    context = {
        'grouped_products': sorted_grouped_products,
        'total_count': len(products),
        'date': datetime.date.today(),
        'generated_by': request.user.get_full_name() or request.user.username
    }
    return render(request, 'product/products_pdf.html', context)
