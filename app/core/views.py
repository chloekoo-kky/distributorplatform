# distributorplatform/app/core/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from inventory.models import Supplier
from product.models import Category
from images.models import ImageCategory
from inventory.views import staff_required # Re-use the staff_required decorator
from django.http import JsonResponse
from django.views.decorators.http import require_POST

# Import forms needed for modals
from inventory.forms import (
    InventoryBatchForm, QuotationUploadForm,
    QuotationCreateForm, InventoryBatchUploadForm
)
import datetime
import json
from django.core.serializers.json import DjangoJSONEncoder

from sales.forms import InvoiceUpdateForm
from product.forms import ProductForm, ProductUploadForm
from images.forms import ImageUploadForm
from sales.models import Invoice
from blog.models import Post
from seo.models import PageMetadata
from sales.models import Invoice

from user.models import UserGroup # Import UserGroup
from .models import Banner
from .forms import BannerForm

# --- Make sure logging is imported ---
import logging
logger = logging.getLogger(__name__)


@staff_required
def manage_dashboard(request):
    """
    Renders the main dashboard shell. All data is loaded asynchronously.
    We only pass in data needed for modals and filters.
    """

    # --- START: ROBUST FILTER DATA GENERATION ---

    # 1. Build the map first, and strip whitespace from all names.
    group_to_categories_map = {}
    all_categories_set = set() # Use a set for unique, flat list

    # --- START MODIFICATION ---
    # Pre-fetch all categories and evaluate into a list *once*
    # This prevents the queryset from being "consumed".
    all_categories_list_from_db = list(Category.objects.select_related('group').all())
    # --- END MODIFICATION ---

    # --- MODIFICATION: Iterate over the new list ---
    for cat in all_categories_list_from_db:
    # --- END MODIFICATION ---
        # Ensure all parts exist and have names
        if cat.group and cat.group.name and cat.name:
            # Strip whitespace to prevent key mismatches
            group_name = cat.group.name.strip()
            cat_name = cat.name.strip()

            if group_name and cat_name: # Ensure they aren't just whitespace
                if group_name not in group_to_categories_map:
                    group_to_categories_map[group_name] = []

                group_to_categories_map[group_name].append(cat_name)
                all_categories_set.add(cat_name)

    # 2. Derive the group list *from the map's keys*
    all_category_groups = sorted(list(group_to_categories_map.keys()))

    # 3. Create the flat list from the set
    all_categories_flat_list = sorted(list(all_categories_set))

    try:
        logger.info(f"[DEBUG] manage_dashboard: CLEANED group_to_categories_map: {json.dumps(group_to_categories_map, indent=2)}")
    except Exception as e:
        logger.error(f"[DEBUG] manage_dashboard: Error logging group_to_categories_map: {e}")
    # --- (End Logging) ---


    # --- Data for Modals ---
    # --- MODIFICATION: Use the new list, but re-sort it as needed for the modal ---
    # We must sort it here to match the old .order_by() behavior for the modal list
    all_categories_list = [
        {'id': cat.id, 'name': str(cat)}
        for cat in sorted(all_categories_list_from_db, key=lambda c: (c.group.name if c.group else '', c.name))
    ]
    # --- END MODIFICATION ---
    all_suppliers_list = [
        {'id': sup.id, 'name': sup.name}
        for sup in Supplier.objects.all().order_by('name')
    ]
    all_image_categories = list(ImageCategory.objects.all().values('id', 'name'))

    # --- START MODIFICATION ---
    # 4. Get User Groups for commission calculation
    all_user_groups = UserGroup.objects.all().order_by('name')
    all_user_groups_list = [
        {'id': g.id, 'name': g.name, 'commission_percentage': g.commission_percentage}
        for g in all_user_groups
    ]
    # --- END MODIFICATION ---


    # 1. For Invoices Tab
    all_invoices = Invoice.objects.select_related(
        'supplier', 'quotation'
    ).prefetch_related(
        'items__product'
    ).order_by('-created_at')

    # 2. For Blog Tab
    all_blog_posts = Post.objects.select_related(
        'author'
    ).prefetch_related(
        'user_groups'
    ).order_by('-created_at')

    # 3. For SEO Tab
    all_seo_settings = PageMetadata.objects.all().order_by('page_path')

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

    context = {
        'title': 'Manage Dashboard',
        'is_subpage': False,

        # --- Filter Data (now guaranteed to match) ---
        'all_category_groups': all_category_groups,
        'all_categories_flat_list': all_categories_flat_list,
        'group_to_categories_map': group_to_categories_map,

        # --- Modal Forms ---
        'quotation_upload_form': QuotationUploadForm(),
        'quotation_create_form': QuotationCreateForm(),
        'inventory_batch_upload_form': InventoryBatchUploadForm(),
        'receive_stock_form': InventoryBatchForm(),
        'invoice_status_choices': Invoice.InvoiceStatus.choices,
        'image_upload_form': ImageUploadForm(),
        'today_date': datetime.date.today(),

        'product_upload_form': ProductUploadForm(),

        'all_categories_list': all_categories_list,
        'all_suppliers_list': all_suppliers_list,

        'all_image_categories_json': json.dumps(all_image_categories),

        'all_user_groups_list': all_user_groups_list, # Pass the new list
        'all_banners_list': all_banners_list,

        'banner_form': BannerForm(),

        'invoices': all_invoices,
        'blog_posts': all_blog_posts,
        'seo_settings': all_seo_settings,
    }

    return render(request, 'core/manage_tools.html', context)


@staff_required
@require_POST
def api_save_banner(request, banner_id=None):
    """Create or Update a banner."""
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
