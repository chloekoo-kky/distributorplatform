# distributorplatform/app/core/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from inventory.models import Supplier
from product.models import Category
from images.models import ImageCategory
from inventory.views import staff_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import datetime
import json
import logging

from inventory.forms import (
    InventoryBatchForm, QuotationUploadForm,
    QuotationCreateForm, InventoryBatchUploadForm
)
from sales.forms import InvoiceUpdateForm
from product.forms import ProductForm, ProductUploadForm
from images.forms import ImageUploadForm
from sales.models import Invoice
from blog.models import Post
from seo.models import PageMetadata
from user.models import UserGroup
from .models import Banner
from .forms import BannerForm

logger = logging.getLogger(__name__)

@staff_required
def manage_dashboard(request):
    """
    Renders the main dashboard shell.
    Refactored to load heavy data (Invoices, Blog Posts) asynchronously via APIs.
    """

    # --- 1. Filter & Dropdown Data (Needed for Modals/Sidebar) ---
    group_to_categories_map = {}
    all_categories_set = set()

    # Pre-fetch categories
    all_categories_list_from_db = list(Category.objects.select_related('group').all())

    for cat in all_categories_list_from_db:
        if cat.group and cat.group.name and cat.name:
            group_name = cat.group.name.strip()
            cat_name = cat.name.strip()
            if group_name and cat_name:
                if group_name not in group_to_categories_map:
                    group_to_categories_map[group_name] = []
                group_to_categories_map[group_name].append(cat_name)
                all_categories_set.add(cat_name)

    all_category_groups = sorted(list(group_to_categories_map.keys()))
    all_categories_flat_list = sorted(list(all_categories_set))

    # Formatted list for modals
    all_categories_list = [
        {'id': cat.id, 'name': str(cat)}
        for cat in sorted(all_categories_list_from_db, key=lambda c: (c.group.name if c.group else '', c.name))
    ]

    all_suppliers_list = [
        {'id': sup.id, 'name': sup.name}
        for sup in Supplier.objects.all().order_by('name')
    ]

    all_image_categories = list(ImageCategory.objects.all().values('id', 'name'))

    all_user_groups = UserGroup.objects.all().order_by('name')
    all_user_groups_list = [
        {'id': g.id, 'name': g.name, 'commission_percentage': g.commission_percentage}
        for g in all_user_groups
    ]

    # --- 2. Lightweight Data (Kept server-side) ---
    # SEO Settings (Usually small table)
    all_seo_settings = PageMetadata.objects.all().order_by('page_path')

    # Banners (Usually small table)
    all_banners = Banner.objects.all().order_by('location', 'order', '-created_at')
    all_banners_list = [{
        'id': b.id,
        'location': b.location,
        'location_display': b.get_location_display(),
        'title': b.title,
        'subtitle': b.subtitle,
        'background_image_url': b.background_image.url if b.background_image else '',
        'background_color': b.background_color,
        'background_opacity': b.background_opacity,
        'content_position': b.content_position,
        'button_text': b.button_text,
        'button_link': b.button_link,
        'is_active': b.is_active,
        'order': b.order
    } for b in all_banners]

    # --- REMOVED HEAVY QUERIES: Invoices & Blog Posts ---
    # These are now fetched via their respective API endpoints in the tabs.

    context = {
        'title': 'Manage Dashboard',
        'is_subpage': False,

        # Filters
        'all_category_groups': all_category_groups,
        'all_categories_flat_list': all_categories_flat_list,
        'group_to_categories_map': group_to_categories_map,

        # Modal Forms
        'quotation_upload_form': QuotationUploadForm(),
        'quotation_create_form': QuotationCreateForm(),
        'inventory_batch_upload_form': InventoryBatchUploadForm(),
        'receive_stock_form': InventoryBatchForm(),
        'invoice_status_choices': Invoice.InvoiceStatus.choices,
        'image_upload_form': ImageUploadForm(),
        'today_date': datetime.date.today(),
        'product_upload_form': ProductUploadForm(),
        'banner_form': BannerForm(),

        # Data Lists for JS
        'all_categories_list': all_categories_list,
        'all_suppliers_list': all_suppliers_list,
        'all_image_categories_json': json.dumps(all_image_categories),
        'all_user_groups_list': all_user_groups_list,
        'all_banners_list': all_banners_list,

        # Kept Data
        'seo_settings': all_seo_settings,
        # 'blog_posts' and 'invoices' removed
    }

    return render(request, 'core/manage_tools.html', context)


@staff_required
@require_POST
def api_save_banner(request, banner_id=None):
    if banner_id:
        banner = get_object_or_404(Banner, pk=banner_id)
        form = BannerForm(request.POST, request.FILES, instance=banner)
    else:
        form = BannerForm(request.POST, request.FILES)

    if form.is_valid():
        banner = form.save()
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@staff_required
@require_POST
def api_delete_banner(request, banner_id):
    banner = get_object_or_404(Banner, pk=banner_id)
    banner.delete()
    return JsonResponse({'success': True})
