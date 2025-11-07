# distributorplatform/app/core/views.py
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from inventory.models import Supplier
from product.models import Category
from images.models import ImageCategory
from inventory.views import staff_required # Re-use the staff_required decorator

# Import forms needed for modals
from inventory.forms import (
    InventoryBatchForm, QuotationUploadForm,
    QuotationCreateForm, InventoryBatchUploadForm
)
import datetime
import json
from django.core.serializers.json import DjangoJSONEncoder

from sales.forms import InvoiceUpdateForm
from product.forms import ProductForm
from images.forms import ImageUploadForm
from sales.models import Invoice
from blog.models import Post
from seo.models import PageMetadata
from sales.models import Invoice

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

    # Pre-fetch all categories with their groups
    all_categories_qs = Category.objects.select_related('group').all()

    for cat in all_categories_qs:
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

    # --- END: ROBUST FILTER DATA GENERATION ---


    # --- (Optional) Log the final, clean map ---
    try:
        logger.info(f"[DEBUG] manage_dashboard: CLEANED group_to_categories_map: {json.dumps(group_to_categories_map, indent=2)}")
    except Exception as e:
        logger.error(f"[DEBUG] manage_dashboard: Error logging group_to_categories_map: {e}")
    # --- (End Logging) ---


    # --- Data for Modals ---
    all_categories_list = [
        {'id': cat.id, 'name': str(cat)}
        for cat in all_categories_qs.order_by('group__name', 'name') # Re-use the query
    ]
    all_suppliers_list = [
        {'id': sup.id, 'name': sup.name}
        for sup in Supplier.objects.all().order_by('name')
    ]
    all_image_categories = list(ImageCategory.objects.all().values('id', 'name'))

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

    context = {
        'title': 'Manage Dashboard',
        'is_subpage': False,

        # --- Filter Data (now guaranteed to match) ---
        'all_category_groups': all_category_groups,
        'all_categories_flat_list': all_categories_flat_list, # Was 'all_categories_flat_list_json'
        'group_to_categories_map': group_to_categories_map,

        # --- Modal Forms ---
        'quotation_upload_form': QuotationUploadForm(),
        'quotation_create_form': QuotationCreateForm(),
        'inventory_batch_upload_form': InventoryBatchUploadForm(),
        'receive_stock_form': InventoryBatchForm(),
        'invoice_status_choices': Invoice.InvoiceStatus.choices,
        'image_upload_form': ImageUploadForm(),
        'today_date': datetime.date.today(),

        # --- Data for Modals (as JSON) ---
        'all_categories_list_json': json.dumps(all_categories_list),
        'all_suppliers_list_json': json.dumps(all_suppliers_list),
        'all_image_categories_json': json.dumps(all_image_categories),

        'invoices': all_invoices,
        'blog_posts': all_blog_posts,
        'seo_settings': all_seo_settings,
    }

    return render(request, 'core/manage_tools.html', context)
