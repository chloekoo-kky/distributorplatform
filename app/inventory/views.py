# distributorplatform/app/inventory/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.db.models import (
    Count, Sum, F, DecimalField, Prefetch,
    Subquery, OuterRef, Q
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse, HttpResponseBadRequest
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from tablib import Dataset
import csv
import datetime
from django.http import HttpResponse
import logging
from decimal import Decimal
from django.core.paginator import Paginator, EmptyPage

from django.core.serializers.json import DjangoJSONEncoder
import json

from .forms import (
    InventoryBatchForm, QuotationUploadForm,
    QuotationCreateForm, InventoryBatchUploadForm
)
from .resources import QuotationResource, InventoryBatchResource
from product.models import Product
from product.models import Product, Category, CategoryGroup
from .models import Quotation, InventoryBatch, QuotationItem, Supplier
from sales.models import Invoice, InvoiceItem
from blog.models import Post
from images.models import MediaImage, ImageCategory
from images.forms import ImageUploadForm
from seo.models import PageMetadata


logger = logging.getLogger(__name__)



def staff_required(view_func):
    """ Decorator to ensure the user is logged in AND is a staff member. """
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You do not have permission to access this page.")
            return redirect('product:product_list')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# --- START: NEW API VIEW FOR INVENTORY TAB ---
@staff_required
def api_manage_inventory(request):
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Filters ---
    search_query = request.GET.get('search', '')
    group_filter = request.GET.get('group', '')
    category_filter = request.GET.get('category', '')
    page_number = request.GET.get('page', 1)

    # --- START ADDED: Log the received filters ---
    logger.info(f"[DEBUG] api_manage_inventory: Received filters: search='{search_query}', group='{group_filter}', category='{category_filter}'")
    # --- END ADDED ---

    # --- 3. Build Base Queryset ---
    queryset = Product.objects.annotate(
        total_stock=Coalesce(Sum('batches__quantity'), 0),
        # --- START REMOVAL ---
        # annotated_base_cost=Subquery(latest_item_price_sq)
        # --- END REMOVAL ---
    ).select_related('featured_image').prefetch_related(
        Prefetch('categories', queryset=Category.objects.select_related('group')),
        Prefetch(
            'quotationitem_set',
            queryset=QuotationItem.objects.select_related('quotation')
                                          .prefetch_related('quotation__items')
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items' # This must match the property check
        )
    ).order_by('name')

    # --- 4. Apply Filters ---
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) | Q(sku__icontains=search_query)
        )
    if group_filter:
        queryset = queryset.filter(categories__group__name=group_filter)
    if category_filter:
        queryset = queryset.filter(categories__name=category_filter)

    queryset = queryset.distinct()

    # --- 5. Paginate ---
    paginator = Paginator(queryset, 50) # 50 items per page
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'products': [], 'pagination': {}})

    # --- 6. Serialize ---
    inventory_products_list = []
    for product in page_obj.object_list:
        category_list = [cat.name for cat in product.categories.all()]
        group_list = [cat.group.name for cat in product.categories.all() if cat.group]

        product_data = {
            'id': product.pk,
            'sku': product.sku or '-',
            'name': product.name,
            'total_stock': product.total_stock or 0,
            'base_cost': product.base_cost,
            'category_groups': sorted(list(set(group_list))),
            'categories': sorted(list(set(category_list))),
            'featured_image_url': product.featured_image.image.url if product.featured_image else None,
            'featured_image_alt': product.featured_image.alt_text if product.featured_image else product.name,
            # Note: We are NOT serializing batch/quotation history here for performance.
            # That could be a separate API call when a row is expanded.
        }
        inventory_products_list.append(product_data)

    # --- 7. Return JSON ---
    return JsonResponse({
        'items': inventory_products_list,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })
# --- END: NEW API VIEW FOR INVENTORY TAB ---


# --- START: NEW API VIEW FOR QUOTATIONS TAB ---
@staff_required
def api_manage_quotations(request):
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Params ---
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    status_filter = request.GET.get('status', '') # 'OPEN' or 'INVOICED'

    # Date Filter
    try:
        month = int(request.GET.get('month', 0))
        year = int(request.GET.get('year', 0))
    except ValueError:
        month = 0
        year = 0

    total_value_calc = Sum(F('items__quantity') * F('items__quoted_price'), output_field=DecimalField())

    queryset = Quotation.objects.annotate(
        annotated_item_count=Count('items'),
        annotated_total_value=total_value_calc
    ).select_related('supplier').prefetch_related(
        'invoice'
    ).order_by('-date_quoted', '-created_at')

    # --- 2. Apply Filters ---

    # Date Filter (date_quoted) - Only filter if month/year are non-zero (All Time logic)
    if month and year:
        queryset = queryset.filter(date_quoted__year=year, date_quoted__month=month)

    # Search Filter
    if search_query:
        queryset = queryset.filter(
            Q(quotation_id__icontains=search_query) |
            Q(supplier__name__icontains=search_query)
        )

    # Status Filter
    if status_filter:
        if status_filter == 'INVOICED':
            queryset = queryset.filter(invoice__isnull=False)
        elif status_filter == 'OPEN':
            queryset = queryset.filter(invoice__isnull=True)

    # --- 3. Pagination ---
    paginator = Paginator(queryset, 50)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    serialized_items = []
    for q in page_obj.object_list:
        # Determine status string for frontend
        status_label = 'Invoiced' if hasattr(q, 'invoice') and q.invoice else 'Open'

        serialized_items.append({
            'quotation_id': q.quotation_id,
            'supplier_name': q.supplier.name,
            'date_quoted': q.date_quoted,
            'status': status_label,
            'item_count': q.annotated_item_count,
            'total_value': q.annotated_total_value or 0,
            'transportation_cost': q.transportation_cost or 0,
            'detail_url': reverse('inventory:quotation_detail', kwargs={'quotation_id': q.quotation_id}),
            'invoice_id': q.invoice.invoice_id if hasattr(q, 'invoice') and q.invoice else None,
        })

    return JsonResponse({
        'items': serialized_items,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        }
    })


@staff_required
def api_get_quotation_items(request, quotation_id):
    """
    Returns a JSON list of all line items for a specific quotation.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        # Ensure quotation exists
        quotation = get_object_or_404(Quotation, quotation_id=quotation_id)

        items = QuotationItem.objects.filter(
            quotation=quotation
        ).select_related(
            'product'
        ).order_by('product__name')

        serialized_items = [
            {
                'product_sku': item.product.sku or '-',
                'product_name': item.product.name,
                'quantity': item.quantity,
                'quoted_price': item.quoted_price,
                'total_price': item.total_item_price,
            }
            for item in items
        ]

        return JsonResponse({'items': serialized_items})

    except Exception as e:
        logger.error(f"Error fetching items for quotation {quotation_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@staff_required
def add_inventory_batch(request):
     """ View for adding Inventory Batches """
     if request.method != 'POST': return redirect('core:manage_dashboard')
     form = InventoryBatchForm(request.POST)
     if form.is_valid():
         try:
             batch = form.save(); messages.success(request, f"Batch {batch.batch_number} added."); return redirect(reverse('core:manage_dashboard') + '#inventory')
         except Exception as e: messages.error(request, f"Error saving batch: {e}")
     else:
         for field, errors in form.errors.items():
             for error in errors: messages.error(request, f"{field.capitalize()}: {error}")
     return redirect(reverse('core:manage_dashboard') + '#inventory')


@staff_required
@transaction.atomic
def receive_stock(request):
    """ Handles POST request from the 'Receive Stock' modal to create an InventoryBatch. """
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        messages.error(request, "Invalid request method.")
        return redirect('core:manage_dashboard')

    # Get the related InvoiceItem for validation
    invoice_item = None
    invoice_item_id = request.POST.get('invoice_item') # Get ID from hidden form field
    if invoice_item_id:
        try:
            invoice_item = InvoiceItem.objects.select_related('invoice').get(pk=invoice_item_id)
        except (InvoiceItem.DoesNotExist, ValueError):
             logger.warning(f"[receive_stock] Invalid or missing invoice_item_id: {invoice_item_id}")
             return JsonResponse({'success': False, 'error': 'Associated invoice item not found.'}, status=400)

    # Pass the instance to the form for validation
    form = InventoryBatchForm(request.POST, invoice_item=invoice_item)

    if form.is_valid():
        try:
            batch = form.save()
            logger.info(f"[receive_stock] Successfully created batch: {batch.batch_number} for product ID {batch.product_id}")

            # --- START Update Invoice Item and Invoice Status ---
            if invoice_item:
                # Recalculate the total received for the specific invoice item
                invoice_item.update_received_quantity()
                # The update_received_quantity method now also calls invoice.update_receive_status()
                logger.info(f"Updated received quantity for InvoiceItem {invoice_item.id} to {invoice_item.quantity_received}.")
                logger.info(f"Invoice {invoice_item.invoice.invoice_id} status updated to {invoice_item.invoice.status}.")
            # --- END Update ---

            return JsonResponse({'success': True, 'batch_number': batch.batch_number})

        except IntegrityError as e:
            logger.error(f"[receive_stock] IntegrityError saving batch: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': f'Database error saving batch: {e}'}, status=500)
        except Exception as e:
            logger.error(f"[receive_stock] Unexpected error saving batch: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {e}'}, status=500)
    else:
        logger.warning(f"[receive_stock] Form validation failed: {form.errors.as_json()}")
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@staff_required
def upload_batches(request):
    """ Handles POST requests for uploading inventory batch files. """
    logger.info("[upload_batches] View called.")
    if request.method != 'POST':
        logger.warning("[upload_batches] GET request received, redirecting.")
        return redirect('core:manage_dashboard')

    redirect_url = reverse('core:manage_dashboard') + '#inventory'
    form = InventoryBatchUploadForm(request.POST, request.FILES)

    if form.is_valid():
        file = request.FILES['file']
        logger.info(f"[upload_batches] Form is valid. Processing file: {file.name}")

        if not file.name.endswith(('.csv', '.xls', '.xlsx')):
            logger.warning(f"[upload_batches] Invalid file format: {file.name}")
            messages.error(request, "Invalid file format. Please upload a .csv, .xls, or .xlsx file.")
            return redirect(redirect_url)

        try:
            dataset = Dataset()
            if file.name.endswith('.csv'):
                logger.info(f"[upload_batches] Reading .csv file: {file.name}")
                file_content = file.read()
                decoded_content = None
                try: decoded_content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    logger.warning("[upload_batches] 'utf-8' decoding failed. Trying 'latin-1'.")
                    decoded_content = file_content.decode('latin-1')
                dataset.load(decoded_content, format='csv')
            else:
                logger.info(f"[upload_batches] Reading excel file: {file.name}")
                dataset.load(file.read(), format='xlsx')
            logger.info("[upload_batches] File read and loaded into dataset.")
        except Exception as e:
            logger.error(f"[upload_batches] Error reading file: {e}", exc_info=True)
            messages.error(request, f"Error reading file: {e}")
            return redirect(redirect_url)

        batch_resource = InventoryBatchResource() # Now defined
        logger.info("[upload_batches] Starting dry run of import...")
        result = batch_resource.import_data(dataset, dry_run=True, use_transactions=True)

        if not result.has_errors() and not result.has_validation_errors():
            try:
                logger.info("[upload_batches] Dry run successful. Starting actual import.")
                with transaction.atomic():
                    batch_resource.import_data(dataset, dry_run=False, use_transactions=True)
                logger.info("[upload_batches] Import successful.")
                messages.success(request, "Inventory batch file imported successfully.")
            except Exception as e:
                logger.error(f"[upload_batches] Error during final import: {e}", exc_info=True)
                messages.error(request, f"An error occurred during import: {e}")
        else:
            errors = result.has_errors() and result.row_errors() or result.base_errors
            logger.warning(f"[upload_batches] Dry run failed. Errors: {errors}")
            if errors:
                for error in errors:
                    try:
                        if isinstance(error, tuple) and len(error) > 1 and error[1]:
                             first_error_instance = error[1][0]
                             msg = f"Error in row {error[0]}: {first_error_instance.error}"
                        elif hasattr(error, 'error'):
                             msg = f"Import Error: {error.error}"
                        else:
                             msg = f"Unknown import error format: {error}"
                        logger.warning(f"[upload_batches] Import error detail: {msg}")
                        messages.warning(request, msg)
                    except (IndexError, AttributeError, TypeError) as report_err:
                        logger.error(f"[upload_batches] Error reporting import error: {report_err}, Original error data: {error}")
                        messages.warning(request, f"An error occurred during import validation, but details could not be displayed. Original data: {error}")

            else:
                logger.error("[upload_batches] Unknown validation error occurred but no specific errors found.")
                messages.error(request, "An unknown error occurred during validation.")
            messages.error(request, "Batch file import failed. Please check messages, correct the file, and try again.")


        return redirect(redirect_url)

    logger.warning(f"[upload_batches] Form was invalid. Errors: {form.errors.as_json()}")
    messages.error(request, "An error occurred with the upload form.")
    return redirect(redirect_url)

@staff_required
def export_batches_csv(request):
    """ Handles the export of all inventory batches to a CSV file. """
    logger.info("[export_batches_csv] View called. Starting export.")
    try:
        batch_resource = InventoryBatchResource() # Now defined
        queryset = InventoryBatch.objects.all().select_related('product', 'supplier', 'quotation')
        dataset = batch_resource.export(queryset)

        response = HttpResponse(dataset.csv, content_type='text/csv')
        filename = f"inventory_batches-{datetime.date.today()}.csv"
        response['Content-Disposition'] = f'attachment; filename={filename}'
        logger.info(f"[export_batches_csv] Successfully created CSV file: {filename}")
        return response
    except Exception as e:
        logger.error(f"[export_batches_csv] Error during export: {e}", exc_info=True)
        messages.error(request, f"An error occurred during export: {e}")
        return redirect(reverse('core:manage_dashboard') + '#inventory')


@staff_required
def create_quotation(request):
    """ Processes the POST request from the 'Create Quotation' modal. """
    logger.info("[create_quotation] Received POST request.") # Log entry
    if request.method != 'POST':
        logger.warning("[create_quotation] Not a POST request, redirecting.")
        return redirect('core:manage_dashboard')

    form = QuotationCreateForm(request.POST)

    if form.is_valid():
        logger.info("[create_quotation] Form is valid.")
        quotation = None
        try:
            # Save supplier from form, but don't commit to DB yet
            quotation = form.save(commit=False)
            # Set the date_quoted to today by default
            quotation.date_quoted = timezone.now().date()
            # Now save the full object (this generates the ID)
            quotation.save()
            logger.info(f"[create_quotation] Quotation saved successfully. ID: {quotation.quotation_id}")

            messages.success(request, f"Quotation {quotation.quotation_id} created.");
            messages.info(request, "You can now add items and other details.")

        except (IntegrityError, Exception) as e:
            # Log the full error if saving fails
            logger.error(f"[create_quotation] Error during quotation save: {e}", exc_info=True)
            messages.error(request, f"Error creating quotation: {e}");
            return redirect(reverse('core:manage_dashboard') + '#quotations')

        # Check if we have a quotation object AND it has an ID after saving
        if quotation and quotation.quotation_id:
            try:
                # Try to generate the redirect URL
                redirect_url = reverse('inventory:quotation_detail', kwargs={'quotation_id': quotation.quotation_id})
                logger.info(f"[create_quotation] Successfully reversed URL: {redirect_url}. Attempting redirect.")
                # If URL generation succeeds, redirect
                return redirect(redirect_url)
            except Exception as e:
                # Log the full error if URL generation or redirect fails
                logger.error(f"[create_quotation] Error during redirect creation/execution: {e}", exc_info=True)
                messages.error(request, f"Quotation created, but redirect failed: {e}");
                return redirect(reverse('core:manage_dashboard') + '#quotations')
        else:
            # This case means something went wrong during save that wasn't an exception
            logger.error("[create_quotation] Quotation object or quotation_id is missing after save attempt.")
            messages.error(request, "Failed to create quotation object properly.");
            return redirect(reverse('core:manage_dashboard') + '#quotations')

    else:
        # Log if the form is invalid
        logger.warning(f"[create_quotation] Form is invalid. Errors: {form.errors.as_json()}")
        for field, errors in form.errors.items():
            for error in errors: messages.error(request, f"Error in {field.capitalize()}: {error}")

    # Fallback redirect if form was invalid or redirect failed above
    logger.info("[create_quotation] Reached end of view (fallback redirect).")
    return redirect(reverse('core:manage_dashboard') + '#quotations')



@staff_required
def quotation_detail(request, quotation_id):
    """ Displays quotation details and allows dynamic editing of items. """
    logger.debug(f"[quotation_detail GET] Request for Quotation ID: {quotation_id}")
    quotation = get_object_or_404(Quotation.objects.select_related('supplier'), quotation_id=quotation_id)
    supplier = quotation.supplier
    # --- START MODIFICATION ---
    current_date = quotation.date_quoted # Get current quotation's date
    # --- END MODIFICATION ---
    logger.debug(f"[quotation_detail GET] Fetched Quotation: {quotation}, Supplier: {supplier.name}")

    # --- Handle POST (AJAX update from Vanilla JS) ---
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        logger.debug(f"[quotation_detail POST] Received AJAX POST request for Quotation ID: {quotation_id}")
        # Check if quotation is already invoiced
        if hasattr(quotation, 'invoice') and quotation.invoice:
             logger.warning(f"[quotation_detail POST] Attempted update on invoiced quotation {quotation_id}")
             return JsonResponse({'success': False, 'error': 'Cannot update items on an invoiced quotation.'}, status=400)

        try:
            data = json.loads(request.body)
            logger.debug(f"[quotation_detail POST] Received payload: {data}")
            items_data = data.get('items', [])

            # --- Get new fields from payload ---
            transport_cost_str = data.get('transportation_cost', str(quotation.transportation_cost))
            date_quoted_str = data.get('date_quoted', str(quotation.date_quoted))
            notes_str = data.get('notes', quotation.notes)
            # --- End new fields ---

            # Validate transport cost
            try:
                new_transport_cost = Decimal(transport_cost_str) if transport_cost_str else Decimal('0.00')
                if new_transport_cost < 0: raise ValueError("Transportation cost cannot be negative.")
                logger.debug(f"[quotation_detail POST] Validated transport cost: {new_transport_cost}")
            except (ValueError, TypeError) as e:
                 logger.error(f"[quotation_detail POST] Invalid transport cost: {transport_cost_str}, Error: {e}")
                 return JsonResponse({'success': False, 'error': 'Invalid transportation cost value.'}, status=400)

            # --- Validate date ---
            try:
                # Use datetime.strptime, not date.strptime
                new_date_quoted = datetime.datetime.strptime(date_quoted_str, '%Y-%m-%d').date()
                logger.debug(f"[quotation_detail POST] Validated date quoted: {new_date_quoted}")
            except (ValueError, TypeError) as e:
                 logger.error(f"[quotation_detail POST] Invalid date quoted: {date_quoted_str}, Error: {e}")
                 return JsonResponse({'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

            # Notes is just a string
            new_notes = notes_str
            # --- End validation ---

            with transaction.atomic():
                # --- Update quotation object ---
                fields_to_update = []
                if quotation.transportation_cost != new_transport_cost:
                    quotation.transportation_cost = new_transport_cost
                    fields_to_update.append('transportation_cost')

                if quotation.date_quoted != new_date_quoted:
                    quotation.date_quoted = new_date_quoted
                    fields_to_update.append('date_quoted')

                if quotation.notes != new_notes:
                    quotation.notes = new_notes
                    fields_to_update.append('notes')

                if fields_to_update:
                    quotation.save(update_fields=fields_to_update)
                    logger.info(f"[quotation_detail POST] Updated fields {fields_to_update} for {quotation_id}")
                # --- End quotation update ---

                # Process items (existing logic)
                existing_items = {item.product_id: item for item in quotation.items.all()}
                product_ids_in_payload = set()
                items_to_update = []
                items_to_create = []

                for item_data in items_data:
                    product_id = item_data.get('product_id')
                    quantity = item_data.get('quantity')
                    price_str = item_data.get('quoted_price')
                    logger.debug(f"[quotation_detail POST] Processing item data: {item_data}")

                    if not product_id or quantity is None or price_str is None:
                        logger.warning(f"[quotation_detail POST] Skipping invalid item data: {item_data}")
                        continue

                    try:
                        quantity = int(quantity)
                        price = Decimal(price_str)
                        if quantity < 0 or price < Decimal('0.00'): raise ValueError("Negative quantity/price")
                    except (ValueError, TypeError):
                        logger.warning(f"[quotation_detail POST] Skipping invalid quantity/price: {item_data}")
                        continue

                    product_ids_in_payload.add(product_id)

                    if quantity > 0:
                        if product_id in existing_items:
                            item = existing_items[product_id]
                            if item.quantity != quantity or item.quoted_price != price:
                                item.quantity = quantity; item.quoted_price = price
                                items_to_update.append(item)
                                logger.debug(f"[quotation_detail POST] Marked item for update: Product ID {product_id}")
                        else:
                            items_to_create.append(QuotationItem(
                                quotation=quotation, product_id=product_id,
                                quantity=quantity, quoted_price=price
                            ))
                            logger.debug(f"[quotation_detail POST] Marked item for creation: Product ID {product_id}")

                ids_to_delete = [pid for pid in existing_items if pid not in product_ids_in_payload]
                if ids_to_delete:
                    deleted_count, _ = QuotationItem.objects.filter(quotation=quotation, product_id__in=ids_to_delete).delete()
                    logger.info(f"[quotation_detail POST] Deleted {deleted_count} items for quotation {quotation_id}")

                if items_to_update:
                    QuotationItem.objects.bulk_update(items_to_update, ['quantity', 'quoted_price'])
                    logger.info(f"[quotation_detail POST] Bulk updated {len(items_to_update)} items for quotation {quotation_id}")

                if items_to_create:
                    QuotationItem.objects.bulk_create(items_to_create)
                    logger.info(f"[quotation_detail POST] Bulk created {len(items_to_create)} items for quotation {quotation_id}")

            logger.info(f"[quotation_detail POST] Successfully updated items for quotation {quotation_id}")
            return JsonResponse({'success': True})

        except json.JSONDecodeError:
            logger.error("[quotation_detail POST] Invalid JSON received", exc_info=True)
            return JsonResponse({'success': False, 'error': 'Invalid JSON data received.'}, status=400)
        except Product.DoesNotExist:
             logger.error("[quotation_detail POST] Invalid product ID in payload", exc_info=True)
             return JsonResponse({'success': False, 'error': 'Invalid product ID found in submitted data.'}, status=400)
        except Exception as e:
            logger.error(f"[quotation_detail POST] Unexpected error updating items: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {e}'}, status=500)

    # --- GET Request (Existing logic) ---
    logger.debug("[quotation_detail GET] Preparing data for template...")
    supplier_products = Product.objects.filter(suppliers=supplier).order_by('name')
    logger.debug(f"[quotation_detail GET] Found {supplier_products.count()} products for supplier {supplier.name}")

    current_items = {item.product_id: item for item in quotation.items.select_related('product').all()}
    logger.debug(f"[quotation_detail GET] Found {len(current_items)} existing items in quotation.")

    # --- START MODIFICATION ---
    # Get the most recent quoted price for each product from this supplier *before* the current quotation's date
    previous_items_qs = QuotationItem.objects.filter(
        quotation__supplier=supplier
    ).exclude(
        quotation=quotation # Exclude the current quotation object
    ).order_by(
        'product_id',
        '-quotation__date_quoted', # Get the most recent date first
        '-id' # Add a tie-breaker for same-day quotations
    ).distinct(
        'product_id'
    )
    # Create a lookup map: {product_id: price}
    previous_prices_map = {item.product_id: item.quoted_price for item in previous_items_qs}
    logger.debug(f"[quotation_detail GET] Found {len(previous_prices_map)} previous prices for this supplier.")
    # --- END MODIFICATION ---

    cart_items = []
    for product in supplier_products:
        # --- START MODIFICATION: Add 'previous_quoted_price' ---
        previous_price = previous_prices_map.get(product.pk)

        item_data = {
            'product_id': product.pk,
            'sku': product.sku or '-',
            'name': product.name,
            'quantity': 0,
            'quoted_price': '0.00',
            'previous_quoted_price': str(previous_price) if previous_price is not None else None # Add the new field
        }
        # --- END MODIFICATION ---

        if product.pk in current_items:
            item = current_items[product.pk]
            item_data['quantity'] = item.quantity
            item_data['quoted_price'] = str(item.quoted_price)
        cart_items.append(item_data)
    logger.debug(f"[quotation_detail GET] Prepared cart_items list.")

    try:
        supplier_products_json_str = json.dumps(cart_items)
        logger.debug("[quotation_detail GET] Successfully serialized cart_items to JSON.")
    except Exception as e:
        logger.error(f"[quotation_detail GET] Failed to serialize cart_items to JSON: {e}", exc_info=True)
        supplier_products_json_str = "[]" # Fallback to empty JSON array
        messages.error(request, "Error preparing product data for display.")

    context = {
        'quotation': quotation,
        'supplier_products_json': supplier_products_json_str,
        'initial_transport_cost': str(quotation.transportation_cost),
        'is_subpage': True,
    }
    logger.debug("[quotation_detail GET] Rendering template...")
    return render(request, 'inventory/quotation_detail.html', context)


@staff_required
def delete_quotation_item(request, pk):
    """ Handles the POST request to delete a QuotationItem. """
    if request.method != 'POST': return redirect('core:manage_dashboard')
    item = get_object_or_404(QuotationItem, pk=pk)
    quotation_id = item.quotation.quotation_id
    if hasattr(item.quotation, 'invoice') and item.quotation.invoice:
         messages.error(request, "Cannot delete items from invoiced quotation.")
    else:
        try: item.delete(); messages.success(request, "Item deleted.")
        except Exception as e: messages.error(request, f"Error deleting item: {e}")
    return redirect('inventory:quotation_detail', quotation_id=quotation_id)

@staff_required
def upload_quotation(request):
    """
    View for Function 1: Quotation (Upload)
    Now only processes POST requests from the modal.
    """
    logger.info("[upload_quotation] View called.")
    if request.method != 'POST':
        logger.warning("[upload_quotation] GET request received, redirecting.")
        return redirect('core:manage_dashboard') # Redirect GET requests

    redirect_url = reverse('core:manage_dashboard') + '#quotations'

    form = QuotationUploadForm(request.POST, request.FILES)
    if form.is_valid():
        file = request.FILES['file']
        logger.info(f"[upload_quotation] Form is valid. Processing file: {file.name}, Content-Type: {file.content_type}")

        if not file.name.endswith(('.csv', '.xls', '.xlsx')):
            logger.warning(f"[upload_quotation] Invalid file format: {file.name}")
            messages.error(request, "Invalid file format. Please upload a .csv, .xls, or .xlsx file.")
            return redirect(redirect_url)

        try:
            dataset = Dataset()
            if file.name.endswith('.csv'):
                logger.info(f"[upload_quotation] Reading .csv file: {file.name}")
                file_content = file.read()
                decoded_content = None

                try:
                    logger.info("[upload_quotation] Attempting to decode with 'utf-8'...")
                    decoded_content = file_content.decode('utf-8')
                    logger.info("[upload_quotation] Successfully decoded with 'utf-8'.")
                except UnicodeDecodeError as e_utf8:
                    logger.warning(f"[upload_quotation] 'utf-8' decoding failed: {e_utf8}. Trying 'latin-1'.")
                    try:
                        decoded_content = file_content.decode('latin-1')
                        logger.info("[upload_quotation] Successfully decoded with 'latin-1'.")
                    except UnicodeDecodeError as e_latin1:
                        logger.error(f"[upload_quotation] CRITICAL: 'latin-1' decoding also failed: {e_latin1}. Both encodings failed.", exc_info=True)
                        messages.error(request, "File encoding error. Could not decode file with 'utf-8' or 'latin-1'. Please re-save your file as 'UTF-8' and try again.")
                        return redirect(redirect_url)

                logger.info("[upload_quotation] Loading decoded CSV content into dataset.")
                dataset.load(decoded_content, format='csv')

            else:
                logger.info(f"[upload_quotation] Reading .xlsx file: {file.name}")
                dataset.load(file.read(), format='xlsx')

            logger.info("[upload_quotation] File read and loaded into dataset successfully.")

        except Exception as e:
            logger.error(f"[upload_quotation] Error reading file or loading dataset: {e}", exc_info=True)
            messages.error(request, f"Error reading file: {e}")
            return redirect(redirect_url)

        quotation_resource = QuotationResource() # Now defined
        logger.info("[upload_quotation] Starting dry run of import...")
        result = quotation_resource.import_data(dataset, dry_run=True)
        logger.info(f"[upload_quotation] Dry run complete. Has errors: {result.has_errors()}, Has validation errors: {result.has_validation_errors()}")

        if not result.has_errors() and not result.has_validation_errors():
            try:
                logger.info("[upload_quotation] Dry run successful. Starting atomic transaction for actual import.")
                with transaction.atomic():
                    quotation_resource.import_data(dataset, dry_run=False)
                logger.info("[upload_quotation] Import successful.")
                messages.success(request, "Quotation file imported successfully.")
            except Exception as e:
                logger.error(f"[upload_quotation] Error during final import transaction: {e}", exc_info=True)
                messages.error(request, f"An error occurred during import: {e}")
        else:
            errors = result.has_errors() and result.row_errors() or result.base_errors
            logger.warning(f"[upload_quotation] Dry run failed. Errors: {errors}")
            if errors:
                for error in errors:
                    if error[1]:
                        msg = f"Error in row {error[0]}: {error[1][0].error}"
                        logger.warning(f"[upload_quotation] Import error detail: {msg}")
                        messages.warning(request, msg)
            else:
                logger.error("[upload_quotation] Unknown validation error occurred.")
                messages.error(request, "An unknown error occurred during validation.")
            messages.error(request, "File import failed with errors. Please correct the file and try again.")

        return redirect(redirect_url)

    logger.warning(f"[upload_quotation] Form was invalid. Errors: {form.errors.as_json()}")
    messages.error(request, "An error occurred with the upload form.")
    return redirect(redirect_url)


@staff_required
def export_quotations_csv(request):
    """
    Handles the export of all quotations and their items to a CSV file.
    """
    response = HttpResponse(content_type='text/csv')
    filename = f"quotations-{datetime.date.today()}.csv"
    response['Content-Disposition'] = f'attachment; filename={filename}'
    writer = csv.writer(response)

    # Write header row
    writer.writerow([
        'Quotation ID',
        'Supplier',
        'Date Quoted',
        'Transportation Cost',
        'Quotation Notes',
        'Product',
        'Quantity',
        'Quoted Price (Unit)',
        'Total Item Price'
    ])

    # Fetch all quotations and related items efficiently
    quotations = Quotation.objects.select_related('supplier').prefetch_related('items__product')

    for quotation in quotations:
        if quotation.items.exists():
            for item in quotation.items.all():
                writer.writerow([
                    quotation.quotation_id,
                    quotation.supplier.name,
                    quotation.date_quoted,
                    quotation.transportation_cost,
                    quotation.notes,
                    item.product.name,
                    item.quantity,
                    item.quoted_price,
                    item.total_item_price, # Using the @property from QuotationItem
                ])
        else:
            # Include quotations even if they have no items
             writer.writerow([
                quotation.quotation_id,
                quotation.supplier.name,
                quotation.date_quoted,
                quotation.transportation_cost,
                quotation.notes,
                'N/A', # No product
                0,     # No quantity
                0.00,  # No price
                0.00,  # No total
            ])

    return response


@staff_required
def api_get_product_batches(request, product_id):
    """
    Returns a JSON list of all inventory batches for a specific product.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        batches = InventoryBatch.objects.filter(
            product_id=product_id
        ).select_related(
            'supplier', 'quotation'
        ).order_by('-received_date')

        # --- START MODIFICATION ---
        # 1. Get all unique quotation IDs from the batches
        quotation_ids = {batch.quotation_id for batch in batches if batch.quotation_id}

        # 2. Find all relevant QuotationItems in one query.
        #    This is for *this product* across *all relevant quotations*.
        #    We prefetch 'quotation__items' so the landed_cost_per_unit property
        #    can calculate efficiently without N+1 queries.
        relevant_quotation_items = QuotationItem.objects.filter(
            product_id=product_id,
            quotation_id__in=quotation_ids
        ).select_related('quotation').prefetch_related('quotation__items')

        # 3. Create a lookup map: {quotation_id: landed_cost}
        cost_map = {
            item.quotation_id: item.landed_cost_per_unit
            for item in relevant_quotation_items
        }
        # --- END MODIFICATION ---

        serialized_batches = []
        for batch in batches:
            # --- START MODIFICATION ---
            # 4. Get the cost from our map
            batch_landed_cost = cost_map.get(batch.quotation_id)

            batch_data = {
                'batch_number': batch.batch_number,
                'supplier_name': batch.supplier.name if batch.supplier else 'N/A',
                'quotation_id': batch.quotation.quotation_id if batch.quotation else 'N/A',
                'quantity': batch.quantity,
                'received_date': batch.received_date,
                'expiry_date': batch.expiry_date or 'N/A',
                'landed_cost': batch_landed_cost # Add the cost here
            }
            # --- END MODIFICATION ---
            serialized_batches.append(batch_data)

        return JsonResponse({'batches': serialized_batches})

    except Exception as e:
        logger.error(f"Error fetching batches for product {product_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)
