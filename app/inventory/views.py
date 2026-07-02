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
from django.views.decorators.http import require_POST
import logging
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json
import re

from .forms import (
    InventoryBatchForm, QuotationUploadForm, InvoiceUploadForm,
    QuotationCreateForm, InventoryBatchUploadForm
)
from .invoice_import import (
    parse_payable_invoice_detail_file,
    suggest_supplier_match,
    suggest_supplier_code,
    confirm_payable_invoice_import,
    _normalize_import_action,
)
from .resources import QuotationResource, InventoryBatchResource
from product.models import Product, Category, CategoryGroup
from product.pricing_sync import sync_saved_base_costs_for_quotation
from .models import (
    Quotation, InventoryBatch, QuotationItem, Supplier,
    SupplierPriceMatrixEntry, SupplierPriceMatrixTier,
    SupplierPriceMatrixUploadRecord,
)
from .supplier_pricing import (
    parse_supplier_price_matrix_file,
    sync_saved_base_costs_for_products,
    list_quotation_matrix_rows,
    serialize_quotation_matrix_item,
    default_matrix_unit_price,
    invoice_item_landed_cost_per_unit,
    _matrix_search_tokens as matrix_search_tokens,
)
from sales.models import Invoice, InvoiceItem
from blog.models import Post
from images.models import MediaImage, ImageCategory
from images.forms import ImageUploadForm
from seo.models import PageMetadata


logger = logging.getLogger(__name__)


def _import_export_user_messages(result):
    """
    Human-readable messages from django-import-export Result.
    base_errors hold Error objects (not tuples); row_errors are (row_number, list of errors).
    """
    lines = []
    seen = set()

    def add(msg):
        if not msg:
            return
        text = str(msg).strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)

    if result.has_errors():
        for err in getattr(result, 'base_errors', []) or []:
            exc = getattr(err, 'error', err)
            add(f"Import error: {exc}")

        for item in result.row_errors():
            if isinstance(item, tuple) and len(item) >= 2:
                row_num, err_list = item[0], item[1]
                for e in err_list or []:
                    exc = getattr(e, 'error', e)
                    add(f"Error in row {row_num}: {exc}")
            else:
                exc = getattr(item, 'error', item)
                add(str(exc))

    for inv in getattr(result, 'invalid_rows', []) or []:
        num = getattr(inv, 'number', '?')
        err = getattr(inv, 'error', inv)
        add(f"Row {num}: {err}")

    return lines



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
                                          .order_by('-quotation__date_quoted'),
            to_attr='latest_quotation_items'
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

    queryset = queryset.filter(total_stock__gt=0).distinct()

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
    ).select_related('supplier', 'invoice').prefetch_related('items').order_by('-date_quoted', '-created_at')

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
        inv = getattr(q, 'invoice', None)
        status_label = 'Invoiced' if inv else 'Open'
        has_orderable_qty = any((it.quantity or 0) > 0 for it in q.items.all())

        serialized_items.append({
            'quotation_id': q.quotation_id,
            'supplier_name': q.supplier.name,
            'date_quoted': q.date_quoted,
            'status': status_label,
            'invoice_status': inv.get_status_display() if inv else None,
            'invoice_status_code': inv.status if inv else None,
            'item_count': q.annotated_item_count,
            'total_value': q.annotated_total_value or 0,
            'transportation_cost': q.transportation_cost or 0,
            'detail_url': reverse('inventory:quotation_detail', kwargs={'quotation_id': q.quotation_id}),
            'invoice_id': inv.invoice_id if inv else None,
            'create_invoice_url': (
                reverse('sales:create_invoice_from_quotation', kwargs={'quotation_id': q.quotation_id})
                if status_label == 'Open' and has_orderable_qty
                else None
            ),
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


def _serialize_procurement_invoice_items(invoice):
    items_data = []
    for item in invoice.items.filter(quantity__gt=0):
        items_data.append({
            'id': item.id,
            'sku': item.product.sku if item.product and item.product.sku else '-',
            'product_name': item.product.name if item.product else (item.description or '-'),
            'description': item.description or '',
            'quantity': item.quantity,
            'quantity_received': item.quantity_received,
            'quantity_remaining': item.quantity - item.quantity_received,
            'unit_price': float(item.unit_price),
            'total_price': float(item.total_price),
            'original_currency': getattr(item, 'original_currency', '') or '',
            'unit_price_source': float(item.unit_price_source) if getattr(item, 'unit_price_source', None) is not None else None,
            'gross_source': float(item.gross_source) if getattr(item, 'gross_source', None) is not None else None,
            'gross_myr': float(item.total_price),
            'is_fully_received': item.is_fully_received,
            'product_id': item.product.id if item.product else None,
        })
    return items_data


def _serialize_procurement_invoice(invoice):
    transport = float(invoice.transportation_cost or 0)
    return {
        'key': f'inv-{invoice.invoice_id}',
        'record_type': 'invoice',
        'document_id': invoice.invoice_id,
        'supplier_name': invoice.supplier.name,
        'supplier_id': invoice.supplier.id,
        'quotation_id': invoice.quotation.quotation_id if invoice.quotation else None,
        'quotation_pk': invoice.quotation.id if invoice.quotation else None,
        'date': invoice.date_issued.isoformat() if invoice.date_issued else None,
        'payment_date': invoice.payment_date.isoformat() if invoice.payment_date else None,
        'status': invoice.get_status_display(),
        'status_code': invoice.status,
        'item_count': invoice.items.filter(quantity__gt=0).count(),
        'transportation_cost': transport,
        'total_amount': float(invoice.total_amount or 0),
        'detail_url': None,
        'create_invoice_url': None,
        'invoice_id': invoice.invoice_id,
        'items': _serialize_procurement_invoice_items(invoice),
    }


def _serialize_procurement_po(quotation, item_count, total_value):
    has_orderable_qty = any((it.quantity or 0) > 0 for it in quotation.items.all())
    transport = float(quotation.transportation_cost or 0)
    goods = float(total_value or 0)
    return {
        'key': f'po-{quotation.quotation_id}',
        'record_type': 'purchase_order',
        'document_id': quotation.quotation_id,
        'supplier_name': quotation.supplier.name,
        'supplier_id': quotation.supplier_id,
        'quotation_id': quotation.quotation_id,
        'quotation_pk': quotation.pk,
        'date': quotation.date_quoted.isoformat() if quotation.date_quoted else None,
        'payment_date': None,
        'status': 'Open',
        'status_code': 'OPEN',
        'item_count': item_count,
        'transportation_cost': transport,
        'total_amount': goods + transport,
        'detail_url': reverse('inventory:quotation_detail', kwargs={'quotation_id': quotation.quotation_id}),
        'create_invoice_url': (
            reverse('sales:create_invoice_from_quotation', kwargs={'quotation_id': quotation.quotation_id})
            if has_orderable_qty else None
        ),
        'delete_quotation_url': reverse(
            'inventory:delete_quotation',
            kwargs={'quotation_id': quotation.quotation_id},
        ),
        'invoice_id': None,
        'items': None,
    }


@staff_required
def api_manage_procurement(request):
    """
    Unified list of open purchase orders and supplier invoices for the Invoices tab.
    Invoiced quotations appear only as invoices (no duplicate PO row).
    """
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    type_filter = request.GET.get('type', '').strip().lower()  # '', 'po', 'invoice'
    status_filter = request.GET.get('status', '').strip().upper()

    try:
        month = int(request.GET.get('month', 0))
        year = int(request.GET.get('year', 0))
    except ValueError:
        month = 0
        year = 0

    sort_by = (request.GET.get('sort_by') or 'date').strip().lower()
    sort_dir = (request.GET.get('sort_dir') or 'desc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    include_po = type_filter in ('', 'po')
    include_invoice = type_filter in ('', 'invoice')

    if status_filter == 'OPEN':
        include_po = True
        include_invoice = False
    elif status_filter and status_filter != 'OPEN':
        include_po = False
        include_invoice = True

    records = []

    if include_po:
        po_qs = (
            Quotation.objects.filter(invoice__isnull=True)
            .annotate(
                annotated_item_count=Count('items', filter=Q(items__quantity__gt=0)),
                annotated_total_value=Sum(
                    F('items__quantity') * F('items__quoted_price'),
                    filter=Q(items__quantity__gt=0),
                    output_field=DecimalField(),
                ),
            )
            .select_related('supplier')
            .prefetch_related('items')
            .order_by('-date_quoted', '-created_at')
        )
        if month and year:
            po_qs = po_qs.filter(date_quoted__year=year, date_quoted__month=month)
        if search_query:
            po_qs = po_qs.filter(
                Q(quotation_id__icontains=search_query)
                | Q(supplier__name__icontains=search_query)
                | Q(items__product__name__icontains=search_query)
            ).distinct()
        for q in po_qs:
            records.append(_serialize_procurement_po(
                q, q.annotated_item_count, q.annotated_total_value,
            ))

    if include_invoice:
        inv_qs = (
            Invoice.objects.select_related('supplier', 'quotation')
            .prefetch_related('items__product')
            .order_by('-date_issued', '-created_at')
        )
        if month and year:
            inv_qs = inv_qs.filter(date_issued__year=year, date_issued__month=month)
        if search_query:
            inv_qs = inv_qs.filter(
                Q(invoice_id__icontains=search_query)
                | Q(supplier__name__icontains=search_query)
                | Q(quotation__quotation_id__icontains=search_query)
                | Q(items__product__name__icontains=search_query)
                | Q(items__description__icontains=search_query)
            ).distinct()
        if status_filter and status_filter != 'OPEN':
            inv_qs = inv_qs.filter(status=status_filter)
        for inv in inv_qs:
            records.append(_serialize_procurement_invoice(inv))

    sort_keys = {
        'type': lambda r: (r.get('record_type') or '').lower(),
        'document': lambda r: (r.get('document_id') or '').lower(),
        'supplier': lambda r: (r.get('supplier_name') or '').lower(),
        'date': lambda r: r.get('date') or '',
        'status': lambda r: (r.get('status_code') or '').lower(),
        'items': lambda r: int(r.get('item_count') or 0),
        'transport': lambda r: float(r.get('transportation_cost') or 0),
        'total': lambda r: float(r.get('total_amount') or 0),
    }
    key_fn = sort_keys.get(sort_by, sort_keys['date'])
    records.sort(key=key_fn, reverse=(sort_dir == 'desc'))

    paginator = Paginator(records, 25)
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        return JsonResponse({'items': [], 'pagination': {}})

    return JsonResponse({
        'items': list(page_obj.object_list),
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        },
    })


@staff_required
def api_get_quotation_items(request, quotation_id):
    """
    Returns a JSON list of all line items for a specific quotation.
    """
    try:
        # Ensure quotation exists
        quotation = get_object_or_404(Quotation, quotation_id=quotation_id)

        items = QuotationItem.objects.filter(
            quotation=quotation,
            quantity__gt=0,
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
            batch = form.save(commit=False)
            batch.batch_number = ''
            batch.save()
            logger.info(f"[receive_stock] Successfully created batch #{batch.pk} for product ID {batch.product_id}")

            # --- START Update Invoice Item and Invoice Status ---
            if invoice_item:
                # Recalculate the total received for the specific invoice item
                invoice_item.update_received_quantity()
                # The update_received_quantity method now also calls invoice.update_receive_status()
                logger.info(f"Updated received quantity for InvoiceItem {invoice_item.id} to {invoice_item.quantity_received}.")
                logger.info(f"Invoice {invoice_item.invoice.invoice_id} status updated to {invoice_item.invoice.status}.")
            # --- END Update ---

            return JsonResponse({'success': True, 'batch_id': batch.pk})

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
@transaction.atomic
def bulk_receive_stock(request):
    """Receive stock for multiple invoice line items in one request."""
    if request.method != 'POST' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=400)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    received_date_str = (payload.get('received_date') or '').strip()
    if not received_date_str:
        return JsonResponse({'success': False, 'error': 'Received date is required.'}, status=400)
    try:
        received_date = datetime.date.fromisoformat(received_date_str)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid received date.'}, status=400)

    raw_items = payload.get('items') or []
    if not raw_items:
        return JsonResponse({'success': False, 'error': 'No items to receive.'}, status=400)

    batches_to_create = []
    invoice_items_to_update = []
    validation_errors = []

    for index, entry in enumerate(raw_items, start=1):
        raw_item_id = entry.get('invoice_item_id') or entry.get('invoiceItemId')
        try:
            invoice_item_id = int(raw_item_id)
        except (TypeError, ValueError):
            validation_errors.append(f'Row {index}: invalid invoice item.')
            continue

        try:
            invoice_item = InvoiceItem.objects.select_related(
                'invoice', 'invoice__quotation', 'product'
            ).get(pk=invoice_item_id)
        except InvoiceItem.DoesNotExist:
            validation_errors.append(f'Row {index}: invoice item not found.')
            continue

        if not invoice_item.product_id:
            validation_errors.append(
                f'Row {index}: {invoice_item.description or invoice_item.id} has no linked product.'
            )
            continue

        if invoice_item.is_fully_received:
            validation_errors.append(
                f'Row {index}: {invoice_item.product.name} is already fully received.'
            )
            continue

        raw_quantity = entry.get('quantity')
        if raw_quantity is None:
            raw_quantity = entry.get('quantity_to_receive')
        if raw_quantity is None:
            quantity = invoice_item.quantity_remaining
        else:
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                validation_errors.append(f'Row {index}: invalid quantity.')
                continue

        if quantity <= 0:
            validation_errors.append(f'Row {index}: quantity must be at least 1.')
            continue
        if quantity > invoice_item.quantity_remaining:
            validation_errors.append(
                f'Row {index}: cannot receive more than {invoice_item.quantity_remaining} for '
                f'{invoice_item.product.name}.'
            )
            continue

        quotation = invoice_item.invoice.quotation
        batches_to_create.append(InventoryBatch(
            product_id=invoice_item.product_id,
            supplier_id=invoice_item.invoice.supplier_id,
            quotation_id=quotation.id if quotation else None,
            invoice_item=invoice_item,
            quantity=quantity,
            received_date=received_date,
            batch_number='',
        ))
        invoice_items_to_update.append(invoice_item)

    if validation_errors:
        return JsonResponse({'success': False, 'errors': validation_errors}, status=400)

    created_batch_ids = []
    for batch in batches_to_create:
        batch.save()
        created_batch_ids.append(batch.pk)

    updated_invoice_ids = set()
    for invoice_item in invoice_items_to_update:
        invoice_item.update_received_quantity()
        updated_invoice_ids.add(invoice_item.invoice.invoice_id)

    logger.info(
        '[bulk_receive_stock] Created %s batch(es) for invoice item IDs: %s',
        len(created_batch_ids),
        [item.pk for item in invoice_items_to_update],
    )

    return JsonResponse({
        'success': True,
        'batch_count': len(created_batch_ids),
        'invoice_ids': sorted(updated_invoice_ids),
    })


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

            messages.success(request, f"Purchase order {quotation.quotation_id} created.")
            messages.info(request, "You can now add items and other details.")

        except (IntegrityError, Exception) as e:
            # Log the full error if saving fails
            logger.error(f"[create_quotation] Error during quotation save: {e}", exc_info=True)
            messages.error(request, f"Error creating purchase order: {e}")
            return redirect(reverse('core:manage_dashboard') + '#invoices')

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
                messages.error(request, f"Purchase order created, but redirect failed: {e}")
                return redirect(reverse('core:manage_dashboard') + '#invoices')
        else:
            # This case means something went wrong during save that wasn't an exception
            logger.error("[create_quotation] Quotation object or quotation_id is missing after save attempt.")
            messages.error(request, "Failed to create purchase order properly.")
            return redirect(reverse('core:manage_dashboard') + '#invoices')

    else:
        # Log if the form is invalid
        logger.warning(f"[create_quotation] Form is invalid. Errors: {form.errors.as_json()}")
        for field, errors in form.errors.items():
            for error in errors: messages.error(request, f"Error in {field.capitalize()}: {error}")

    # Fallback redirect if form was invalid or redirect failed above
    logger.info("[create_quotation] Reached end of view (fallback redirect).")
    return redirect(reverse('core:manage_dashboard') + '#invoices')



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
             return JsonResponse({'success': False, 'error': 'Cannot update items on an invoiced purchase order.'}, status=400)

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
                    input_currency = item_data.get('input_currency') or None
                    input_value_str = item_data.get('input_value')
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

                    input_value = None
                    if input_value_str is not None and input_value_str != '':
                        try:
                            input_value = Decimal(str(input_value_str))
                            if input_value < Decimal('0.00'):
                                input_value = None
                        except (ValueError, TypeError):
                            pass
                    if input_currency and input_currency not in ('EUR', 'USD', 'MYR'):
                        input_currency = None

                    product_ids_in_payload.add(product_id)

                    if quantity >= 0:
                        if product_id in existing_items:
                            item = existing_items[product_id]
                            if (item.quantity != quantity or item.quoted_price != price or
                                    getattr(item, 'input_currency', None) != input_currency or
                                    getattr(item, 'input_value', None) != input_value):
                                item.quantity = quantity
                                item.quoted_price = price
                                item.input_currency = input_currency
                                item.input_value = input_value
                                items_to_update.append(item)
                                logger.debug(f"[quotation_detail POST] Marked item for update: Product ID {product_id}")
                        else:
                            prod_name = Product.objects.filter(pk=product_id).values_list('name', flat=True).first()
                            new_item = QuotationItem(
                                quotation=quotation, product_id=product_id,
                                quantity=quantity, quoted_price=price,
                                line_product_label=(prod_name or '')[:255],
                            )
                            new_item.input_currency = input_currency
                            new_item.input_value = input_value
                            items_to_create.append(new_item)
                            logger.debug(f"[quotation_detail POST] Marked item for creation: Product ID {product_id}")

                ids_to_delete = [pid for pid in existing_items if pid not in product_ids_in_payload]
                if ids_to_delete:
                    deleted_count, _ = QuotationItem.objects.filter(quotation=quotation, product_id__in=ids_to_delete).delete()
                    logger.info(f"[quotation_detail POST] Deleted {deleted_count} items for quotation {quotation_id}")

                if items_to_update:
                    QuotationItem.objects.bulk_update(items_to_update, ['quantity', 'quoted_price', 'input_currency', 'input_value'])
                    logger.info(f"[quotation_detail POST] Bulk updated {len(items_to_update)} items for quotation {quotation_id}")

                if items_to_create:
                    QuotationItem.objects.bulk_create(items_to_create)
                    logger.info(f"[quotation_detail POST] Bulk created {len(items_to_create)} items for quotation {quotation_id}")

                sync_saved_base_costs_for_quotation(quotation)

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

    # --- START FIX: Show products for supplier OR products already in quotation ---
    # This ensures that if a product is removed from the supplier list but is still in the quotation,
    # it doesn't disappear from the view.
    quotation_product_ids = quotation.items.values_list('product_id', flat=True)
    supplier_products = Product.objects.filter(
        Q(suppliers=supplier) | Q(id__in=quotation_product_ids)
    ).distinct().order_by('name')
    # --- END FIX ---

    # Products which are NOT yet assigned to this supplier (for the "Add product" selector)
    unassigned_products = Product.objects.exclude(suppliers=supplier).order_by('name')

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

    product_ids = list(supplier_products.values_list('pk', flat=True))
    matrix_entries_qs = (
        SupplierPriceMatrixEntry.objects.filter(supplier=supplier, product_id__in=product_ids)
        .prefetch_related('tiers')
        .order_by('-updated_at')
    )
    matrix_by_product: dict[int, SupplierPriceMatrixEntry] = {}
    currency_counts: dict[str, int] = {}
    for entry in matrix_entries_qs:
        if entry.product_id and entry.product_id not in matrix_by_product:
            matrix_by_product[entry.product_id] = entry
        cur = entry.price_currency or 'MYR'
        currency_counts[cur] = currency_counts.get(cur, 0) + 1
    supplier_matrix_currency = (
        max(currency_counts, key=currency_counts.get) if currency_counts else 'MYR'
    )
    supplier_matrix_conversion_rate = None
    if supplier_matrix_currency != 'MYR':
        latest_for_currency = matrix_entries_qs.filter(
            price_currency=supplier_matrix_currency,
            conversion_rate__isnull=False,
        ).first()
        if latest_for_currency:
            supplier_matrix_conversion_rate = latest_for_currency.conversion_rate

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
            'previous_quoted_price': str(previous_price) if previous_price is not None else None,
            'input_currency': None,
            'input_value': None,
        }
        # --- END MODIFICATION ---

        if product.pk in current_items:
            item = current_items[product.pk]
            item_data['quantity'] = item.quantity
            item_data['quoted_price'] = str(item.quoted_price)
            if getattr(item, 'input_currency', None):
                item_data['input_currency'] = item.input_currency
            if item.input_value is not None:
                item_data['input_value'] = str(item.input_value)

        matrix_entry = matrix_by_product.get(product.pk)
        if matrix_entry:
            matrix_myr = default_matrix_unit_price(matrix_entry)
            matrix_currency = matrix_entry.price_currency or 'MYR'
            if matrix_myr is not None:
                has_line_price = Decimal(item_data['quoted_price'] or '0') > 0
                if not has_line_price:
                    item_data['quoted_price'] = str(matrix_myr)
                line_currency = item_data['input_currency'] or None
                should_apply_matrix_currency = (
                    matrix_currency != 'MYR'
                    and (not line_currency or line_currency == 'MYR')
                )
                if should_apply_matrix_currency:
                    item_data['input_currency'] = matrix_currency
                    original = _matrix_myr_to_original(
                        Decimal(item_data['quoted_price']),
                        matrix_currency,
                        matrix_entry.conversion_rate,
                    )
                    if original is not None:
                        item_data['input_value'] = str(original)
                elif not line_currency and matrix_currency == 'MYR':
                    item_data['input_currency'] = 'MYR'
                    item_data['input_value'] = str(matrix_myr)
                elif (
                    not item_data['input_value']
                    and line_currency
                    and line_currency != 'MYR'
                    and matrix_entry.conversion_rate
                ):
                    original = _matrix_myr_to_original(
                        Decimal(item_data['quoted_price']),
                        line_currency,
                        matrix_entry.conversion_rate,
                    )
                    if original is not None:
                        item_data['input_value'] = str(original)

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
        'unassigned_products': unassigned_products,
        'supplier_matrix_currency': supplier_matrix_currency,
        'supplier_matrix_conversion_rate': (
            str(supplier_matrix_conversion_rate)
            if supplier_matrix_conversion_rate is not None else ''
        ),
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
def delete_quotation(request, quotation_id):
    """Delete an open purchase order that has not been converted to an invoice."""
    if request.method != 'POST':
        return redirect(reverse('core:manage_dashboard') + '#invoices')

    quotation = get_object_or_404(Quotation, quotation_id=quotation_id)

    if Invoice.objects.filter(quotation=quotation).exists():
        messages.error(request, "Cannot delete a purchase order that has been converted to an invoice.")
        return redirect('inventory:quotation_detail', quotation_id=quotation_id)

    if InventoryBatch.objects.filter(quotation=quotation).exists():
        messages.error(request, "Cannot delete this purchase order because stock has been received against it.")
        return redirect('inventory:quotation_detail', quotation_id=quotation_id)

    try:
        quotation.delete()
        messages.success(request, f"Purchase order {quotation_id} deleted.")
    except Exception as e:
        logger.error(f"Error deleting quotation {quotation_id}: {e}", exc_info=True)
        messages.error(request, f"Error deleting purchase order: {e}")
        return redirect('inventory:quotation_detail', quotation_id=quotation_id)

    return redirect(reverse('core:manage_dashboard') + '#invoices')


def _normalize_import_headers(row_dict):
    """Normalize dict keys to lowercase for flexible column matching."""
    return {str(k).strip().lower(): v for k, v in (row_dict or {}).items()}


def _get_import_row_value(normalized_row, *candidate_keys):
    """Get first non-empty value from row for any of the candidate keys (lowercase)."""
    for key in candidate_keys:
        val = normalized_row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _parse_quotation_import_file(file):
    """
    Parse CSV or Excel file for quotation item import.
    Returns (list of dicts, error_message).
    Each dict: product_name, product_sku, quantity, quoted_price (str).
    """
    if not file.name.endswith(('.csv', '.xls', '.xlsx')):
        return None, "Invalid file format. Use .csv, .xls, or .xlsx."
    try:
        dataset = Dataset()
        if file.name.endswith('.csv'):
            file_content = file.read()
            try:
                decoded = file_content.decode('utf-8')
            except UnicodeDecodeError:
                decoded = file_content.decode('latin-1')
            dataset.load(decoded, format='csv')
        else:
            dataset.load(file.read(), format='xlsx')
    except Exception as e:
        return None, str(e)
    if not dataset.height:
        return [], None
    rows = []
    for i, row in enumerate(dataset.dict):
        nr = _normalize_import_headers(row)
        product_name = _get_import_row_value(nr, 'product', 'product name', 'product name ')
        product_sku = _get_import_row_value(nr, 'product sku', 'sku')
        category_str = _get_import_row_value(nr, 'category', 'category name')
        qty_str = _get_import_row_value(nr, 'quantity', 'qty')
        price_str = _get_import_row_value(nr, 'quoted price (unit)', 'quoted price', 'price')
        if not product_name and not product_sku:
            continue
        rows.append({
            'row_index': i + 1,
            'product_name': product_name or '',
            'product_sku': product_sku or '',
            'category': category_str or '',
            'quantity': qty_str,
            'quoted_price': price_str,
        })
    return rows, None


def _resolve_category(category_str):
    """
    Resolve category by code (exact) or by name (case-insensitive, first match). Returns (Category or None, display_name).
    """
    if not category_str or not str(category_str).strip():
        return None, ''
    raw = str(category_str).strip()
    # Try by unique code first
    cat = Category.objects.filter(code__iexact=raw).select_related('group').first()
    if cat:
        return cat, str(cat)
    # Then by name (any group)
    cat = Category.objects.filter(name__iexact=raw).select_related('group').first()
    if cat:
        return cat, str(cat)
    # Optional: name contains (e.g. partial match)
    cat = Category.objects.filter(name__icontains=raw).select_related('group').first()
    if cat:
        return cat, str(cat)
    return None, raw


def _normalize_product_name_for_match(value):
    """
    Prepare a product name for fuzzy matching:
    - Use only the part before '|' (English name)
    - Normalise common unit patterns like '100u', '100U', '100 Unit', '100Units'
      so they all compare the same.
    - Strip special characters
    - Lowercase and collapse whitespace
    """
    if not value:
        return "", []

    base = str(value).split("|", 1)[0]

    # Normalise common unit notations so that e.g.
    # "Wondertox 100u" and "WONDERTOX 100Unit" are treated as the same tokens.
    # Examples handled:
    #   100u, 100U, 100 u, 100 U, 100unit, 100 units, 100 Units  ->  "100unit"
    base = re.sub(
        r"(\d+)\s*(u|unit|units)\b",
        r"\1unit",
        base,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", base).lower()
    tokens = [t for t in cleaned.split() if t]
    return " ".join(tokens), tokens


def _name_similarity(tokens_a, tokens_b):
    """
    Very simple token overlap similarity between two token lists.
    Returns a float between 0 and 1.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    overlap = len(set_a & set_b)
    return (2.0 * overlap) / (len(set_a) + len(set_b))


def _resolve_product_by_sku_or_name(sku, name, *, allow_fuzzy=True):
    """
    Resolve product by SKU (exact) or by name using a fuzzy, token-based match.
    Returns (product, match_type) or (None, 'new').
    """
    # 1) Strong signal: exact SKU match
    if sku:
        try:
            p = Product.objects.get(sku__iexact=sku)
            return p, "matched_sku"
        except Product.DoesNotExist:
            pass

    if not name:
        return None, "new"

    # 2) Exact name match (case-insensitive)
    exact = Product.objects.filter(name__iexact=name).first()
    if exact:
        return exact, "matched_name_exact"

    if not allow_fuzzy:
        return None, "new"

    # 3) Fuzzy name match: token overlap on a small candidate set
    normalized, tokens = _normalize_product_name_for_match(name)
    if not tokens:
        return None, "new"

    # Use the first significant token to narrow the queryset
    first_token = tokens[0]
    candidates_qs = Product.objects.filter(
        Q(name__icontains=first_token) | Q(sku__icontains=first_token)
    ).only("id", "name", "sku")[:30]

    best_product = None
    best_score = 0.0
    for candidate in candidates_qs:
        cand_norm, cand_tokens = _normalize_product_name_for_match(candidate.name)
        score = _name_similarity(tokens, cand_tokens)
        # Light boost if the candidate SKU contains any of the tokens
        if candidate.sku:
            sku_lower = candidate.sku.lower()
            if any(t in sku_lower for t in tokens):
                score += 0.15
        if score > best_score:
            best_score = score
            best_product = candidate

    # Require a minimum similarity so obviously different products don't get auto-mapped
    if best_product and best_score >= 0.55:
        return best_product, "matched_name_fuzzy"

    return None, "new"


@staff_required
def import_quotation_items_preview(request, quotation_id):
    """
    POST with file: parse file and return preview rows with product mapping (matched or new).
    Used when importing items into a specific quotation.
    """
    quotation = get_object_or_404(Quotation.objects.select_related('supplier'), quotation_id=quotation_id)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)
    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'ok': False, 'error': 'No file provided'}, status=400)
    rows, parse_error = _parse_quotation_import_file(file)
    if parse_error is not None:
        return JsonResponse({'ok': False, 'error': parse_error}, status=400)
    preview_rows = []
    errors = []
    for r in rows:
        qty_str = r.get('quantity') or ''
        price_str = r.get('quoted_price') or ''
        try:
            qty = int(qty_str) if qty_str else 0
        except ValueError:
            errors.append(f"Row {r['row_index']}: Invalid quantity '{qty_str}'.")
            continue
        try:
            price = Decimal(price_str) if price_str else Decimal('0')
        except Exception:
            errors.append(f"Row {r['row_index']}: Invalid quoted price '{price_str}'.")
            continue
        if qty < 1:
            errors.append(f"Row {r['row_index']}: Quantity must be at least 1.")
            continue
        if price < 0:
            errors.append(f"Row {r['row_index']}: Quoted price cannot be negative.")
            continue
        product, match_type = _resolve_product_by_sku_or_name(r.get('product_sku'), r.get('product_name'))
        name_for_new = (r.get('product_name') or '').strip() or (r.get('product_sku') or '').strip() or f"Imported item {r['row_index']}"
        imported_category = (r.get('category') or '').strip()
        category_obj, category_display = _resolve_category(imported_category) if imported_category else (None, '')
        preview_rows.append({
            'row_index': r['row_index'],
            'product_id': product.id if product else None,
            'product_sku': product.sku if product else None,
            'product_name': product.name if product else None,
            'quantity': qty,
            'quoted_price': str(price),
            'match_type': match_type,
            'imported_name': r.get('product_name') or '',
            'imported_sku': r.get('product_sku') or '',
            'imported_category': imported_category,
            'category_id': category_obj.id if category_obj else None,
            'category_name': category_display,
            'new_product_name': name_for_new if match_type == 'new' else None,
            'new_product_sku': (r.get('product_sku') or '').strip() or None if match_type == 'new' else None,
        })
    return JsonResponse({
        'ok': True,
        'rows': preview_rows,
        'errors': errors,
        'quotation_id': quotation_id,
    })


@staff_required
def import_quotation_items_confirm(request, quotation_id):
    """
    POST JSON: { "rows": [ { product_id?, new_product_name?, new_product_sku?, quantity, quoted_price } ] }.
    For each row: use product_id if present; else create product with new_product_name (and optional new_product_sku).
    Then create or update QuotationItem for this quotation.
    """
    quotation = get_object_or_404(Quotation.objects.select_related('supplier'), quotation_id=quotation_id)
    if hasattr(quotation, 'invoice') and quotation.invoice:
        return JsonResponse({'success': False, 'error': 'Cannot import items into an invoiced quotation.'}, status=400)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    rows = data.get('rows') or []
    if not rows:
        return JsonResponse({'success': False, 'error': 'No rows provided'}, status=400)
    supplier = quotation.supplier
    errors = []
    created_products = []
    try:
        with transaction.atomic():
            for i, row in enumerate(rows):
                product_id = row.get('product_id')
                new_name = (row.get('new_product_name') or '').strip()
                new_sku = (row.get('new_product_sku') or '').strip() or None
                try:
                    qty = int(row.get('quantity'))
                    price = Decimal(str(row.get('quoted_price', 0)))
                except (ValueError, TypeError):
                    errors.append(f"Row {i + 1}: Invalid quantity or quoted price.")
                    continue
                if qty < 1 or price < 0:
                    errors.append(f"Row {i + 1}: Quantity must be ≥ 1 and price ≥ 0.")
                    continue
                input_currency = row.get('input_currency') or None
                if input_currency and input_currency not in ('EUR', 'USD', 'MYR'):
                    input_currency = None
                input_value = row.get('input_value')
                if input_value is not None and input_value != '':
                    try:
                        input_value = Decimal(str(input_value))
                    except (ValueError, TypeError):
                        input_value = None
                else:
                    input_value = None
                product = None
                if product_id:
                    try:
                        product = Product.objects.get(pk=product_id)
                    except Product.DoesNotExist:
                        errors.append(f"Row {i + 1}: Product ID {product_id} not found.")
                        continue
                else:
                    if not new_name:
                        errors.append(f"Row {i + 1}: Either product_id or new_product_name is required.")
                        continue
                    category_id = row.get('category_id')
                    product = Product.objects.filter(name__iexact=new_name).first()
                    if product:
                        if new_sku and not product.sku and not Product.objects.filter(sku=new_sku).exclude(pk=product.pk).exists():
                            product.sku = new_sku
                            product.save(update_fields=['sku'])
                    else:
                        sku_to_use = new_sku if new_sku and not Product.objects.filter(sku=new_sku).exists() else None
                        product = Product.objects.create(name=new_name, description='', sku=sku_to_use)
                        created_products.append(product.id)
                    if not product.suppliers.filter(pk=supplier.pk).exists():
                        product.suppliers.add(supplier)
                    if category_id and product:
                        try:
                            cat = Category.objects.get(pk=category_id)
                            if not product.categories.filter(pk=cat.pk).exists():
                                product.categories.add(cat)
                        except Category.DoesNotExist:
                            pass
                line_lbl = ((row.get('imported_name') or row.get('line_product_label') or '').strip()[:255])
                if not line_lbl:
                    line_lbl = (product.name or '')[:255]

                existing_item = QuotationItem.objects.filter(quotation=quotation, product=product).first()
                if existing_item:
                    existing_item.quantity = qty
                    existing_item.quoted_price = price
                    existing_item.line_product_label = line_lbl
                    existing_item.input_currency = input_currency
                    existing_item.input_value = input_value
                    existing_item.save(update_fields=['quantity', 'quoted_price', 'line_product_label', 'input_currency', 'input_value'])
                else:
                    item = QuotationItem.objects.create(
                        quotation=quotation, product=product, quantity=qty, quoted_price=price,
                        line_product_label=line_lbl,
                        input_currency=input_currency,
                        input_value=input_value,
                    )
                    # When product was just created from this import, set base cost from this quote so Set Product Pricing shows it.
                    if product.id in created_products:
                        landed = item.landed_cost_per_unit
                        if landed is not None:
                            product.saved_base_cost = landed
                            product.saved_base_cost_supplier = supplier
                            product.save(update_fields=['saved_base_cost', 'saved_base_cost_supplier'])
    except Exception as e:
        logger.exception("import_quotation_items_confirm failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    sync_saved_base_costs_for_quotation(quotation)
    return JsonResponse({
        'success': True,
        'message': f"Imported {len(rows)} item(s).",
        'created_products_count': len(created_products),
    })


@staff_required
def api_products_for_mapping(request):
    """GET ?q=... returns products for import mapping dropdown (id, name, sku)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    q = (request.GET.get('q') or '').strip()[:100]
    if not q:
        products = Product.objects.all().order_by('name')[:50]
    else:
        products = Product.objects.filter(
            Q(name__icontains=q) | Q(sku__icontains=q)
        ).order_by('name')[:30]
    return JsonResponse({
        'products': [{'id': p.id, 'name': p.name, 'sku': p.sku or ''} for p in products],
    })


@staff_required
def assign_product_to_supplier(request, quotation_id):
    """
    Assign an existing Product to the supplier of this quotation so it appears
    in the quotation's product list.
    """
    quotation = get_object_or_404(Quotation.objects.select_related('supplier'), quotation_id=quotation_id)
    supplier = quotation.supplier

    if request.method != 'POST':
        return redirect('inventory:quotation_detail', quotation_id=quotation_id)

    product_ids = request.POST.getlist('product_ids') or []
    # Fallback for old single-select form
    single_id = request.POST.get('product_id')
    if single_id:
        product_ids.append(single_id)

    if not product_ids:
        messages.error(request, "Please select at least one product to assign.")
        return redirect('inventory:quotation_detail', quotation_id=quotation_id)

    assigned = 0
    already = 0
    for pid in product_ids:
        try:
            product = Product.objects.get(pk=pid)
        except Product.DoesNotExist:
            continue
        if product.suppliers.filter(pk=supplier.pk).exists():
            already += 1
        else:
            product.suppliers.add(supplier)
            assigned += 1

    if assigned:
        messages.success(request, f"Assigned {assigned} product(s) to supplier {supplier.name}.")
    if already and not assigned:
        messages.info(request, "All selected products were already assigned to this supplier.")

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

    redirect_url = reverse('core:manage_dashboard') + '#invoices'

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
                messages.success(request, "Purchase order file imported successfully.")
            except Exception as e:
                logger.error(f"[upload_quotation] Error during final import transaction: {e}", exc_info=True)
                messages.error(request, f"An error occurred during import: {e}")
        else:
            err_msgs = _import_export_user_messages(result)
            logger.warning(f"[upload_quotation] Dry run failed. Messages: {err_msgs}")
            for msg in err_msgs:
                messages.warning(request, msg)
            if not err_msgs:
                messages.error(request, "Import failed validation. Check column headers match the export template and try again.")
            messages.error(request, "File import failed with errors. Please correct the file and try again.")

        return redirect(redirect_url)

    logger.warning(f"[upload_quotation] Form was invalid. Errors: {form.errors.as_json()}")
    messages.error(request, "An error occurred with the upload form.")
    return redirect(redirect_url)


def _load_import_dataset(file):
    """Read a .csv or Excel upload into a tablib Dataset."""
    dataset = Dataset()
    if file.name.endswith('.csv'):
        file_content = file.read()
        decoded_content = None
        try:
            decoded_content = file_content.decode('utf-8')
        except UnicodeDecodeError:
            decoded_content = file_content.decode('latin-1')
        dataset.load(decoded_content, format='csv')
    else:
        dataset.load(file.read(), format='xlsx')
    return dataset


@staff_required
def upload_invoice_preview(request):
    """POST multipart: Payable Invoice Detail .xlsx → parsed supplier groups."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)
    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'ok': False, 'error': 'No file provided'}, status=400)

    try:
        parsed, parse_error = parse_payable_invoice_detail_file(file)
        if parse_error:
            return JsonResponse({'ok': False, 'error': parse_error}, status=400)

        for sup in parsed['suppliers']:
            suggestion = suggest_supplier_match(sup['file_supplier_name'], Supplier)
            sup['suggested_supplier_id'] = suggestion['supplier_id']
            sup['suggested_supplier_name'] = suggestion['supplier_name']
            sup['suggested_match_type'] = suggestion['match_type']
            sup['action'] = 'map' if suggestion['supplier_id'] else 'create'
            sup['supplier_id'] = suggestion['supplier_id']
            sup['new_supplier_name'] = sup['file_supplier_name']
            invoice_refs = [inv.get('reference') for inv in sup.get('invoices') or []]
            sup['suggested_supplier_code'] = suggest_supplier_code(
                sup['file_supplier_name'],
                Supplier,
                invoice_refs=invoice_refs,
            )

        return JsonResponse({
            'ok': True,
            'parsed': parsed,
            'source_filename': file.name,
        }, encoder=DjangoJSONEncoder)
    except Exception as exc:
        logger.exception('upload_invoice_preview failed')
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@staff_required
def upload_invoice_confirm(request):
    """POST JSON: supplier mappings + parsed invoice data → import."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    suppliers = data.get('suppliers')
    if not suppliers:
        return JsonResponse({'success': False, 'error': 'No supplier data to import.'}, status=400)

    active = [s for s in suppliers if _normalize_import_action(s.get('action')) != 'ignore']
    if not active:
        return JsonResponse({'success': False, 'error': 'All suppliers are ignored. Nothing to import.'}, status=400)

    try:
        with transaction.atomic():
            stats = confirm_payable_invoice_import(
                {
                    'source_filename': data.get('source_filename') or '',
                    'suppliers': suppliers,
                },
                product_model=Product,
                supplier_model=Supplier,
                invoice_model=Invoice,
                invoice_item_model=InvoiceItem,
            )
    except ValueError as exc:
        logger.warning('upload_invoice_confirm validation failed: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except IntegrityError as exc:
        logger.warning('upload_invoice_confirm integrity error: %s', exc)
        return JsonResponse(
            {'success': False, 'error': 'Database conflict during import. Check for duplicate invoice IDs or supplier codes.'},
            status=400,
        )
    except Exception as exc:
        logger.exception('upload_invoice_confirm failed')
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    parts = []
    if stats['invoices_created']:
        parts.append(f"{stats['invoices_created']} invoice(s) created")
    if stats['invoices_updated']:
        parts.append(f"{stats['invoices_updated']} invoice(s) updated")
    if stats['invoices_skipped']:
        parts.append(f"{stats['invoices_skipped']} skipped (linked to PO)")
    if stats['products_created']:
        parts.append(f"{stats['products_created']} product(s) created")
    if stats['products_matched']:
        parts.append(f"{stats['products_matched']} existing product(s) used")
    if stats.get('matrix_rows_updated'):
        parts.append(f"{stats['matrix_rows_updated']} supplier price row(s) updated")
    message = 'Import complete: ' + ', '.join(parts) if parts else 'Import complete.'

    return JsonResponse({'success': True, 'message': message, 'stats': stats})


@staff_required
def upload_invoice(request):
    """Legacy redirect — invoice import uses preview/confirm via AJAX."""
    messages.info(request, 'Use Import invoice on the Invoices tab to upload a Payable Invoice Detail file.')
    return redirect(reverse('core:manage_dashboard') + '#invoices')


@staff_required
def export_quotations_xlsx(request):
    """
    Export all quotations and line items to Excel (.xlsx).
    Column layout matches QuotationResource import expectations.
    """
    from openpyxl import Workbook

    def _export_unit_usd(item):
        if item.input_currency == QuotationItem.INPUT_CURRENCY_USD and item.input_value is not None:
            return float(item.input_value)
        return None

    wb = Workbook()
    ws = wb.active
    ws.title = 'Quotations'

    headers = [
        'Quotation ID',
        'Supplier',
        'Date Quoted',
        'Transportation Cost',
        'Quotation Notes',
        'Product SKU',
        'Quotation line product name',
        'System product name',
        'Quantity',
        'Quoted Price (USD)',
        'Quoted Price (MYR)',
        'Total Item Price',
        'Base Cost (MYR)',
    ]
    ws.append(headers)

    quotations = Quotation.objects.select_related('supplier').prefetch_related('items__product')
    for quotation in quotations:
        if quotation.items.exists():
            for item in quotation.items.all():
                sys_name = item.product.name if item.product else ''
                line_name = (item.line_product_label or '').strip() or sys_name
                usd = _export_unit_usd(item)
                landed = item.landed_cost_per_unit
                ws.append([
                    quotation.quotation_id,
                    quotation.supplier.name,
                    quotation.date_quoted,
                    float(quotation.transportation_cost or 0),
                    quotation.notes or '',
                    item.product.sku if item.product else '',
                    line_name,
                    sys_name,
                    int(item.quantity),
                    usd,
                    float(item.quoted_price),
                    float(item.total_item_price),
                    float(landed) if landed is not None else None,
                ])
        else:
            ws.append([
                quotation.quotation_id,
                quotation.supplier.name,
                quotation.date_quoted,
                float(quotation.transportation_cost or 0),
                quotation.notes or '',
                '',
                'N/A',
                'N/A',
                0,
                None,
                0.0,
                0.0,
                None,
            ])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    fname = f'quotations-{datetime.date.today()}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    wb.save(response)
    return response


def _parse_matrix_export_keys(keys_param: str) -> tuple[list[int], list[int]]:
    matrix_ids: list[int] = []
    quotation_ids: list[int] = []
    for part in (keys_param or '').split(','):
        part = part.strip()
        if ':' not in part:
            continue
        source, _, pk = part.partition(':')
        if not pk.isdigit():
            continue
        pk_int = int(pk)
        if source == 'matrix':
            matrix_ids.append(pk_int)
        elif source == 'quotation':
            quotation_ids.append(pk_int)
    return matrix_ids, quotation_ids


def _matrix_export_datetime(value):
    if not value:
        return ''
    if isinstance(value, datetime.datetime):
        dt = value
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        return dt.replace(tzinfo=None)
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
        if timezone.is_aware(parsed):
            parsed = timezone.localtime(parsed)
        return parsed.replace(tzinfo=None)
    return str(value)


def _matrix_export_round_usd(value) -> object:
    if value == '' or value is None:
        return ''
    return round(float(value), 2)


def _matrix_export_price_fields(row: dict, tier: dict | None) -> tuple[object, object]:
    """Return original-currency unit price (USD column) and MYR unit price."""
    currency = (row.get('price_currency') or 'MYR').upper()
    rate = row.get('conversion_rate')
    myr_price = tier.get('unit_price') if tier else None

    if myr_price is None:
        return '', ''

    myr_f = round(float(myr_price), 2)
    if currency == 'MYR':
        return '', myr_f

    input_value = row.get('input_value')
    if input_value is not None:
        return _matrix_export_round_usd(input_value), myr_f

    if rate is not None and float(rate) > 0:
        return _matrix_export_round_usd(myr_f / float(rate)), myr_f

    return '', myr_f


def _matrix_export_row_values(row: dict, tier: dict | None) -> list:
    usd_price, myr_price = _matrix_export_price_fields(row, tier)
    return [
        row.get('line_medication') or '',
        row.get('product_name') or '',
        row.get('strength') or '',
        row.get('size') or '',
        row.get('supplier_name') or '',
        tier.get('min_quantity') if tier else '',
        usd_price,
        myr_price,
        _matrix_export_datetime(row.get('updated_at')),
    ]


def _matrix_updated_sort_value(row) -> str:
    raw = row.get('updated_at')
    if not raw:
        return ''
    if isinstance(raw, datetime.datetime):
        return raw.isoformat()
    if isinstance(raw, datetime.date):
        return raw.isoformat()
    return str(raw)


def _matrix_row_sort_key(row, sort_by: str):
    if sort_by == 'updated_at':
        return (
            _matrix_updated_sort_value(row),
            (row.get('line_medication') or '').lower(),
            (row.get('product_name') or '').lower(),
        )
    medication = (row.get('line_medication') or '').lower()
    product = (row.get('product_name') or row.get('line_medication') or '').lower()
    primary = medication if sort_by == 'medication' else product
    return (
        primary,
        medication,
        product,
        (row.get('supplier_name') or '').lower(),
        row.get('strength') or '',
        row.get('size') or '',
    )


def _normalize_matrix_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, bool]:
    sort_by = (sort_by or 'medication').strip()
    sort_dir = (sort_dir or 'asc').strip().lower()
    if sort_by not in ('medication', 'product', 'updated_at'):
        sort_by = 'medication'
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'asc'
    return sort_by, sort_dir == 'desc'


def _parse_matrix_supplier_ids(raw: str | None) -> list[int]:
    if not raw or not str(raw).strip():
        return []
    ids: list[int] = []
    for part in str(raw).split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return list(dict.fromkeys(ids))


def _list_filtered_matrix_rows(
    supplier_ids: list[int] | None = None,
    search_query: str = '',
    sort_by: str = 'medication',
    sort_dir: str = 'asc',
) -> list[dict]:
    supplier_ids = supplier_ids or []
    queryset = (
        SupplierPriceMatrixEntry.objects.select_related('supplier', 'product')
        .prefetch_related('tiers')
    )
    if supplier_ids:
        queryset = queryset.filter(supplier_id__in=supplier_ids)
    if search_query:
        queryset = _filter_matrix_by_search(queryset, search_query)

    matrix_items = [_serialize_matrix_entry(entry) for entry in queryset]
    quotation_items = list_quotation_matrix_rows(
        supplier_ids=supplier_ids or None,
        search_query=search_query,
    )
    combined = matrix_items + quotation_items
    sort_by, reverse = _normalize_matrix_sort(sort_by, sort_dir)
    combined.sort(key=lambda row: _matrix_row_sort_key(row, sort_by), reverse=reverse)
    return combined


def _matrix_rows_for_export_from_dicts(combined_rows: list[dict]) -> list[dict]:
    quotation_ids = [row['id'] for row in combined_rows if row.get('source') == 'quotation']
    item_map: dict[int, QuotationItem] = {}
    if quotation_ids:
        items = (
            QuotationItem.objects.filter(pk__in=quotation_ids)
            .select_related('product', 'quotation', 'quotation__supplier')
            .prefetch_related('quotation__items')
        )
        item_map = {item.pk: item for item in items}

    export_rows: list[dict] = []
    for row in combined_rows:
        export_row = dict(row)
        if export_row.get('source') == 'quotation':
            item = item_map.get(export_row['id'])
            if item and item.input_value is not None and (item.input_currency or 'MYR') != 'MYR':
                export_row['input_value'] = item.input_value
        export_rows.append(export_row)
    return export_rows


def _matrix_export_rows_by_keys(matrix_ids: list[int], quotation_ids: list[int]) -> list[dict]:
    export_rows: list[dict] = []
    if matrix_ids:
        entries = (
            SupplierPriceMatrixEntry.objects.filter(pk__in=matrix_ids)
            .select_related('supplier', 'product')
            .prefetch_related('tiers')
        )
        entry_map = {entry.id: entry for entry in entries}
        for entry_id in matrix_ids:
            entry = entry_map.get(entry_id)
            if entry:
                export_rows.append(_serialize_matrix_entry(entry))

    if quotation_ids:
        items = (
            QuotationItem.objects.filter(pk__in=quotation_ids)
            .select_related('product', 'quotation', 'quotation__supplier')
            .prefetch_related('quotation__items')
        )
        item_map = {item.pk: item for item in items}
        for item_id in quotation_ids:
            item = item_map.get(item_id)
            if item:
                row = serialize_quotation_matrix_item(item)
                if item.input_value is not None and (item.input_currency or 'MYR') != 'MYR':
                    row['input_value'] = item.input_value
                export_rows.append(row)
    return export_rows


def _build_matrix_export_xlsx_response(export_rows: list[dict], filename: str) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = 'Supplier prices'
    headers = [
        'Medication',
        'Catalog product',
        'Strength',
        'Size',
        'Supplier',
        'Min qty',
        'Unit price USD',
        'Unit price MYR',
        'Last updated',
    ]
    ws.append(headers)

    for row in export_rows:
        tiers = row.get('tiers') or []
        if tiers:
            for tier in tiers:
                ws.append(_matrix_export_row_values(row, tier))
        else:
            ws.append(_matrix_export_row_values(row, None))

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


MATRIX_EXPORT_ALL_MAX = 5000


@staff_required
def export_supplier_price_matrix_xlsx(request):
    """Export supplier price matrix rows (selected keys or all rows matching filters)."""
    export_all = (request.GET.get('all') or '').strip().lower() in ('1', 'true', 'yes')

    if export_all:
        supplier_ids = _parse_matrix_supplier_ids(request.GET.get('supplier', ''))
        search_query = request.GET.get('search', '').strip()
        sort_by = request.GET.get('sort_by', 'medication')
        sort_dir = request.GET.get('sort_dir', 'asc')
        combined = _list_filtered_matrix_rows(supplier_ids, search_query, sort_by, sort_dir)
        if not combined:
            messages.error(request, 'No rows match the current filters.')
            return redirect(reverse('core:manage_dashboard') + '#quotations')
        if len(combined) > MATRIX_EXPORT_ALL_MAX:
            messages.error(
                request,
                f'Too many rows to export ({len(combined)}). Narrow filters (max {MATRIX_EXPORT_ALL_MAX}).',
            )
            return redirect(reverse('core:manage_dashboard') + '#quotations')
        export_rows = _matrix_rows_for_export_from_dicts(combined)
        fname = f'supplier-price-matrix-all-{datetime.date.today()}.xlsx'
        return _build_matrix_export_xlsx_response(export_rows, fname)

    keys_param = (request.GET.get('keys') or '').strip()
    matrix_ids, quotation_ids = _parse_matrix_export_keys(keys_param)
    if not matrix_ids and not quotation_ids:
        messages.error(request, 'No rows selected for export.')
        return redirect(reverse('core:manage_dashboard') + '#quotations')

    matrix_ids = list(dict.fromkeys(matrix_ids))[:500]
    quotation_ids = list(dict.fromkeys(quotation_ids))[:500]
    export_rows = _matrix_export_rows_by_keys(matrix_ids, quotation_ids)
    fname = f'supplier-price-matrix-selected-{datetime.date.today()}.xlsx'
    return _build_matrix_export_xlsx_response(export_rows, fname)


MATRIX_DELETE_MAX = 500


@staff_required
def api_delete_supplier_price_matrix_rows(request):
    """POST JSON: { keys: ['matrix:1', 'quotation:2', ...] } — delete matrix catalog rows."""
    if not (request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    raw_keys = payload.get('keys') or []
    if not raw_keys or not isinstance(raw_keys, list):
        return JsonResponse({'success': False, 'error': 'No rows selected.'}, status=400)

    if len(raw_keys) > MATRIX_DELETE_MAX:
        return JsonResponse(
            {'success': False, 'error': f'Too many rows selected (max {MATRIX_DELETE_MAX}).'},
            status=400,
        )

    keys_param = ','.join(str(k) for k in raw_keys)
    matrix_ids, quotation_ids = _parse_matrix_export_keys(keys_param)
    matrix_ids = list(dict.fromkeys(matrix_ids))[:MATRIX_DELETE_MAX]

    if not matrix_ids and not quotation_ids:
        return JsonResponse({'success': False, 'error': 'No valid rows selected.'}, status=400)

    if not matrix_ids:
        return JsonResponse({
            'success': False,
            'error': (
                'Selected rows come from purchase orders and cannot be deleted from the price matrix. '
                'Remove them on the purchase order or upload a price list to replace them.'
            ),
            'skipped_quotation_count': len(quotation_ids),
        }, status=400)

    skipped_quotation_count = len(quotation_ids)
    with transaction.atomic():
        qs = SupplierPriceMatrixEntry.objects.filter(pk__in=matrix_ids)
        deleted_entries = qs.count()
        qs.delete()

    return JsonResponse({
        'success': True,
        'deleted_count': deleted_entries,
        'skipped_quotation_count': skipped_quotation_count,
    })


@staff_required
def api_get_product_batches(request, product_id):
    """
    Returns a JSON list of all inventory batches for a specific product.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        batches = list(
            InventoryBatch.objects.filter(product_id=product_id)
            .select_related('supplier', 'quotation', 'invoice_item', 'invoice_item__invoice')
            .order_by('-received_date')
        )

        # Batch-fetch quotation totals for landed cost (legacy PO path)
        quotation_ids = {b.quotation_id for b in batches if b.quotation_id}
        from django.db.models import DecimalField, ExpressionWrapper, F as Ff, Sum
        quotation_totals = {}
        if quotation_ids:
            for row in (
                QuotationItem.objects.filter(quotation_id__in=quotation_ids)
                .values('quotation_id')
                .annotate(total=Sum(ExpressionWrapper(Ff('quantity') * Ff('quoted_price'), output_field=DecimalField(max_digits=20, decimal_places=4))))
            ):
                if row['total'] is not None:
                    quotation_totals[row['quotation_id']] = Decimal(str(row['total']))

        relevant_quotation_items = {
            item.quotation_id: item
            for item in QuotationItem.objects.filter(
                product_id=product_id, quotation_id__in=quotation_ids
            ).select_related('quotation')
        }

        # Batch-fetch invoice subtotals for landed cost (direct invoice receive path)
        invoice_ids = {
            b.invoice_item.invoice_id
            for b in batches
            if b.invoice_item_id and b.invoice_item
        }
        invoice_subtotals = {}
        if invoice_ids:
            for row in (
                InvoiceItem.objects.filter(invoice_id__in=invoice_ids)
                .values('invoice_id')
                .annotate(
                    total=Sum(
                        ExpressionWrapper(
                            Ff('quantity') * Ff('unit_price'),
                            output_field=DecimalField(max_digits=20, decimal_places=4),
                        )
                    )
                )
            ):
                if row['total'] is not None:
                    invoice_subtotals[row['invoice_id']] = Decimal(str(row['total']))

        serialized_batches = []
        for batch in batches:
            batch_landed_cost = None

            # Prefer invoice line cost when batch came from Receive Stock
            inv_item = batch.invoice_item
            if inv_item and inv_item.quantity and inv_item.unit_price is not None:
                batch_landed_cost = invoice_item_landed_cost_per_unit(
                    inv_item,
                    invoice_subtotals.get(inv_item.invoice_id),
                )
            elif batch.quotation_id:
                qi = relevant_quotation_items.get(batch.quotation_id)
                if qi and qi.quantity and qi.quoted_price:
                    qty = Decimal(str(qi.quantity))
                    price = qi.quoted_price
                    transport = qi.quotation.transportation_cost or Decimal('0')
                    qtotal = quotation_totals.get(batch.quotation_id, Decimal('0'))
                    if qtotal > 0 and transport > 0:
                        item_total = qty * price
                        batch_landed_cost = (item_total + transport * (item_total / qtotal)) / qty
                    else:
                        batch_landed_cost = price

            # Resolve invoice number: prefer the linked invoice item's invoice, else quotation id
            invoice_number = None
            if batch.invoice_item and batch.invoice_item.invoice:
                invoice_number = batch.invoice_item.invoice.invoice_id
            elif batch.quotation:
                invoice_number = batch.quotation.quotation_id

            serialized_batches.append({
                'id': batch.pk,
                'invoice_item_id': batch.invoice_item_id,
                'batch_number': batch.batch_number or '',
                'supplier_name': batch.supplier.name if batch.supplier else 'N/A',
                'invoice_number': invoice_number or '—',
                'quantity': batch.quantity,
                'received_date': batch.received_date,
                'expiry_date': batch.expiry_date.isoformat() if batch.expiry_date else None,
                'landed_cost': batch_landed_cost,
            })

        return JsonResponse({'batches': serialized_batches})

    except Exception as e:
        logger.error(f"Error fetching batches for product {product_id}: {e}", exc_info=True)
        return JsonResponse({'error': 'Internal server error'}, status=500)


@staff_required
def api_get_invoice_item_batches(request, invoice_item_id):
    """GET: all inventory batches linked to one invoice line (one receipt)."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    invoice_item = get_object_or_404(
        InvoiceItem.objects.select_related('invoice', 'product'),
        pk=invoice_item_id,
    )
    batches = (
        InventoryBatch.objects.filter(invoice_item=invoice_item)
        .select_related('supplier')
        .order_by('pk')
    )
    rows = [{
        'id': b.pk,
        'batch_number': b.batch_number or '',
        'expiry_date': b.expiry_date.isoformat() if b.expiry_date else None,
        'quantity': b.quantity,
    } for b in batches]
    total_qty = sum(b.quantity for b in batches)
    return JsonResponse({
        'invoice_item_id': invoice_item.pk,
        'invoice_number': invoice_item.invoice.invoice_id,
        'product_name': invoice_item.product.name if invoice_item.product else '',
        'total_quantity': total_qty,
        'batches': rows,
    })


@staff_required
@require_POST
@transaction.atomic
def api_save_invoice_item_batches(request, invoice_item_id):
    """POST: split/update multiple batch rows for one invoice receipt."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    invoice_item = get_object_or_404(
        InvoiceItem.objects.select_related('invoice', 'product'),
        pk=invoice_item_id,
    )

    try:
        data = json.loads(request.body)
    except (ValueError, KeyError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    incoming_rows = data.get('batches') or []
    if not incoming_rows:
        return JsonResponse({'error': 'At least one batch row is required.'}, status=400)

    existing = list(
        InventoryBatch.objects.filter(invoice_item=invoice_item).order_by('pk')
    )
    if not existing:
        return JsonResponse({'error': 'No receipt batches found for this invoice line.'}, status=404)

    original_total = sum(b.quantity for b in existing)
    template = existing[0]

    parsed_rows = []
    for row in incoming_rows:
        try:
            qty = int(row.get('quantity') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid quantity.'}, status=400)
        if qty <= 0:
            return JsonResponse({'error': 'Each batch row must have a quantity greater than zero.'}, status=400)

        batch_number = (row.get('batch_number') or '').strip()
        expiry_date_raw = (row.get('expiry_date') or '').strip()
        expiry_date = None
        if expiry_date_raw:
            try:
                expiry_date = datetime.date.fromisoformat(expiry_date_raw)
            except ValueError:
                return JsonResponse({'error': 'Invalid expiry date format. Use YYYY-MM-DD.'}, status=400)

        row_id = row.get('id')
        if row_id is not None:
            try:
                row_id = int(row_id)
            except (TypeError, ValueError):
                return JsonResponse({'error': 'Invalid batch id.'}, status=400)

        parsed_rows.append({
            'id': row_id,
            'batch_number': batch_number,
            'expiry_date': expiry_date,
            'quantity': qty,
        })

    new_total = sum(r['quantity'] for r in parsed_rows)
    if new_total != original_total:
        return JsonResponse({
            'error': f'Total quantity must stay {original_total} (currently {new_total}). Adjust row quantities when splitting.',
        }, status=400)

    existing_map = {b.pk: b for b in existing}
    kept_ids = set()

    for row in parsed_rows:
        if row['id'] and row['id'] in existing_map:
            batch = existing_map[row['id']]
            batch.batch_number = row['batch_number']
            batch.expiry_date = row['expiry_date']
            batch.quantity = row['quantity']
            batch.save(update_fields=['batch_number', 'expiry_date', 'quantity'])
            kept_ids.add(batch.pk)
        else:
            batch = InventoryBatch.objects.create(
                product=invoice_item.product,
                supplier=template.supplier,
                quotation=template.quotation,
                invoice_item=invoice_item,
                received_date=template.received_date,
                batch_number=row['batch_number'],
                expiry_date=row['expiry_date'],
                quantity=row['quantity'],
            )
            kept_ids.add(batch.pk)

    for batch in existing:
        if batch.pk not in kept_ids:
            batch.delete()

    invoice_item.update_received_quantity()

    saved = InventoryBatch.objects.filter(invoice_item=invoice_item).order_by('pk')
    return JsonResponse({
        'success': True,
        'batches': [{
            'id': b.pk,
            'batch_number': b.batch_number or '',
            'expiry_date': b.expiry_date.isoformat() if b.expiry_date else None,
            'quantity': b.quantity,
        } for b in saved],
    })


@staff_required
@require_POST
def api_update_batch(request, batch_id):
    """AJAX: update a standalone batch (no invoice line group)."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    batch = get_object_or_404(InventoryBatch, pk=batch_id)

    if batch.invoice_item_id:
        return JsonResponse({
            'error': 'Use batch group save for invoice-linked receipts.',
        }, status=400)

    try:
        data = json.loads(request.body)
    except (ValueError, KeyError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    batch_number = (data.get('batch_number') or '').strip()
    expiry_date_raw = (data.get('expiry_date') or '').strip()

    batch.batch_number = batch_number

    if expiry_date_raw:
        try:
            batch.expiry_date = datetime.date.fromisoformat(expiry_date_raw)
        except ValueError:
            return JsonResponse({'error': 'Invalid expiry date format. Use YYYY-MM-DD.'}, status=400)
    else:
        batch.expiry_date = None

    if 'quantity' in data:
        try:
            qty = int(data.get('quantity') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid quantity.'}, status=400)
        if qty <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero.'}, status=400)
        batch.quantity = qty

    batch.save()
    return JsonResponse({
        'success': True,
        'batch_number': batch.batch_number,
        'expiry_date': batch.expiry_date.isoformat() if batch.expiry_date else None,
        'quantity': batch.quantity,
    })


def _filter_matrix_by_search(queryset, search_query: str):
    """
    Each token must match at least one searchable field (AND across tokens).
    Handles multi-word queries and double-spaces in stored medication names.
    """
    for token in matrix_search_tokens(search_query):
        queryset = queryset.filter(
            Q(line_medication__icontains=token)
            | Q(strength__icontains=token)
            | Q(size__icontains=token)
            | Q(form__icontains=token)
            | Q(notes__icontains=token)
            | Q(product__name__icontains=token)
            | Q(product__sku__icontains=token)
            | Q(supplier__name__icontains=token)
        )
    return queryset


def _matrix_tier_key(min_qty, max_qty):
    return (int(min_qty), int(max_qty) if max_qty is not None else None)


def _normalize_matrix_tiers_for_json(tiers) -> list[dict]:
    """Serialize tier rows (model instances or dicts) for JSON storage/comparison."""
    normalized = []
    for tier in tiers:
        if hasattr(tier, 'min_quantity'):
            min_qty = tier.min_quantity
            max_qty = tier.max_quantity
            unit_price = tier.unit_price
        else:
            min_qty = tier.get('min_quantity', 1)
            max_qty = tier.get('max_quantity')
            unit_price = tier.get('unit_price')
        normalized.append({
            'min_quantity': int(min_qty),
            'max_quantity': int(max_qty) if max_qty not in (None, '') else None,
            'unit_price': str(Decimal(str(unit_price)).quantize(Decimal('0.01'))),
        })
    normalized.sort(key=lambda t: t['min_quantity'])
    return normalized


def _format_matrix_tier_label(min_qty, max_qty) -> str:
    upper = str(max_qty) if max_qty is not None else '+'
    return f"{min_qty}–{upper}"


def _enrich_matrix_tier_snapshots(
    tiers: list | None,
    price_currency: str | None,
    conversion_rate,
) -> list | None:
    """Derive unit_price_source on legacy snapshots for consistent USD/EUR display."""
    if not tiers:
        return tiers
    enriched = []
    currency = (price_currency or 'MYR').upper()
    for tier in tiers:
        t = dict(tier)
        if (
            not t.get('unit_price_source')
            and currency != 'MYR'
            and conversion_rate
            and t.get('unit_price') is not None
        ):
            try:
                myr = Decimal(str(t['unit_price']))
                rate = Decimal(str(conversion_rate))
                if rate > 0:
                    t['unit_price_source'] = str((myr / rate).quantize(Decimal('0.0001')))
            except (InvalidOperation, ZeroDivisionError, TypeError):
                pass
        enriched.append(t)
    return enriched


def _tier_snapshot_compare_price(tier: dict) -> Decimal:
    """Price used for matrix history diffs; prefers invoice source currency when stored."""
    source = tier.get('unit_price_source')
    if source not in (None, ''):
        return Decimal(str(source))
    return Decimal(str(tier['unit_price']))


def _diff_matrix_tier_snapshots(previous_tiers, current_tiers) -> list[dict]:
    """Compare two tier snapshots; previous may be None for first upload."""
    if not previous_tiers:
        return []

    prev_map = {_matrix_tier_key(t['min_quantity'], t['max_quantity']): t for t in previous_tiers}
    curr_map = {_matrix_tier_key(t['min_quantity'], t['max_quantity']): t for t in current_tiers}
    changes = []

    for key, curr in curr_map.items():
        label = _format_matrix_tier_label(key[0], key[1])
        prev = prev_map.get(key)
        curr_price = _tier_snapshot_compare_price(curr)
        if prev is None:
            changes.append({
                'change_type': 'added',
                'tier_label': label,
                'min_quantity': key[0],
                'max_quantity': key[1],
                'new_price': curr_price,
                'new_price_myr': Decimal(curr['unit_price']),
                'new_price_source': curr.get('unit_price_source'),
            })
        else:
            prev_price = _tier_snapshot_compare_price(prev)
            prev_cmp = prev_price.quantize(Decimal('0.01'))
            curr_cmp = curr_price.quantize(Decimal('0.01'))
            if prev_cmp != curr_cmp:
                delta = curr_price - prev_price
                changes.append({
                    'change_type': 'changed',
                    'tier_label': label,
                    'min_quantity': key[0],
                    'max_quantity': key[1],
                    'old_price': prev_price,
                    'new_price': curr_price,
                    'delta': delta,
                    'old_price_myr': Decimal(prev['unit_price']),
                    'new_price_myr': Decimal(curr['unit_price']),
                    'old_price_source': prev.get('unit_price_source'),
                    'new_price_source': curr.get('unit_price_source'),
                })

    for key, prev in prev_map.items():
        if key not in curr_map:
            label = _format_matrix_tier_label(key[0], key[1])
            changes.append({
                'change_type': 'removed',
                'tier_label': label,
                'min_quantity': key[0],
                'max_quantity': key[1],
                'old_price': _tier_snapshot_compare_price(prev),
                'old_price_myr': Decimal(prev['unit_price']),
                'old_price_source': prev.get('unit_price_source'),
            })

    changes.sort(key=lambda c: c['min_quantity'])
    return changes


def _serialize_matrix_entry(entry):
    return {
        'id': entry.id,
        'source': 'matrix',
        'supplier_id': entry.supplier_id,
        'supplier_name': entry.supplier.name,
        'product_id': entry.product_id,
        'product_name': entry.product.name if entry.product else None,
        'product_sku': entry.product.sku if entry.product else None,
        'line_medication': entry.line_medication,
        'strength': entry.strength,
        'form': entry.form,
        'size': entry.size,
        'notes': entry.notes,
        'price_currency': entry.price_currency,
        'conversion_rate': entry.conversion_rate,
        'source_filename': entry.source_filename,
        'effective_date': entry.effective_date,
        'updated_at': entry.updated_at,
        'tiers': [
            {
                'min_quantity': tier.min_quantity,
                'max_quantity': tier.max_quantity,
                'unit_price': tier.unit_price,
            }
            for tier in entry.tiers.all()
        ],
    }


@staff_required
def api_manage_supplier_prices(request):
    """GET: paginated supplier price matrix rows."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    supplier_ids = _parse_matrix_supplier_ids(request.GET.get('supplier', ''))
    search_query = request.GET.get('search', '').strip()
    page_number = request.GET.get('page', 1)
    try:
        limit = int(request.GET.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    if limit not in (25, 50, 100, 200):
        limit = 50

    sort_by = request.GET.get('sort_by', 'medication')
    sort_dir = request.GET.get('sort_dir', 'asc')
    combined = _list_filtered_matrix_rows(supplier_ids, search_query, sort_by, sort_dir)

    paginator = Paginator(combined, limit)
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        return JsonResponse({
            'items': [],
            'pagination': {
                'current_page': 1,
                'total_pages': 0,
                'total_count': 0,
                'page_size': limit,
                'has_next': False,
                'has_previous': False,
            },
        })

    return JsonResponse({
        'items': page_obj.object_list,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
            'page_size': limit,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        },
    }, encoder=DjangoJSONEncoder)


@staff_required
def api_quotation_matrix_row_detail(request, item_id):
    """GET: legacy quotation line as matrix-style row with quotation price history."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    item = get_object_or_404(
        QuotationItem.objects.select_related('product', 'quotation', 'quotation__supplier')
        .prefetch_related('quotation__items'),
        pk=item_id,
    )
    product = item.product
    supplier = item.quotation.supplier

    if SupplierPriceMatrixEntry.objects.filter(supplier=supplier, product=product).exists():
        return JsonResponse({'error': 'This product uses the price matrix for this supplier.'}, status=404)

    history_items = list(
        QuotationItem.objects.filter(product=product, quotation__supplier=supplier)
        .select_related('quotation')
        .prefetch_related('quotation__items')
        .order_by('-quotation__date_quoted', '-pk')
    )

    history = []
    for i, qi in enumerate(history_items):
        cost = qi.landed_cost_per_unit
        if cost is None:
            continue
        tiers = _normalize_matrix_tiers_for_json([{
            'min_quantity': 1,
            'max_quantity': None,
            'unit_price': cost,
        }])
        previous = None
        for j in range(i + 1, len(history_items)):
            prev_cost = history_items[j].landed_cost_per_unit
            if prev_cost is not None:
                previous = _normalize_matrix_tiers_for_json([{
                    'min_quantity': 1,
                    'max_quantity': None,
                    'unit_price': prev_cost,
                }])
                break
        q = qi.quotation
        history.append({
            'id': qi.pk,
            'uploaded_at': q.date_quoted.isoformat() if q.date_quoted else None,
            'source_filename': f'Quotation {q.quotation_id}',
            'price_currency': qi.input_currency or 'MYR',
            'conversion_rate': None,
            'tiers': tiers,
            'changes': _diff_matrix_tier_snapshots(previous, tiers),
        })

    return JsonResponse({
        'entry': serialize_quotation_matrix_item(item),
        'history': history,
    }, encoder=DjangoJSONEncoder)


@staff_required
def api_supplier_price_matrix_entry_detail(request, entry_id):
    """GET: matrix entry with upload history and tier price changes."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    entry = get_object_or_404(
        SupplierPriceMatrixEntry.objects.select_related('supplier', 'product').prefetch_related('tiers'),
        pk=entry_id,
    )
    records = list(entry.upload_records.order_by('-effective_date', '-uploaded_at'))
    enriched_tiers_list = [
        _enrich_matrix_tier_snapshots(r.tiers, r.price_currency, r.conversion_rate)
        for r in records
    ]
    history = []
    for i, record in enumerate(records):
        tiers = enriched_tiers_list[i]
        previous = enriched_tiers_list[i + 1] if i + 1 < len(enriched_tiers_list) else None
        history.append({
            'id': record.id,
            'uploaded_at': record.uploaded_at,
            'effective_date': record.effective_date,
            'source_filename': record.source_filename,
            'price_currency': record.price_currency,
            'conversion_rate': record.conversion_rate,
            'tiers': tiers,
            'changes': _diff_matrix_tier_snapshots(previous, tiers),
        })

    return JsonResponse({
        'entry': _serialize_matrix_entry(entry),
        'history': history,
    }, encoder=DjangoJSONEncoder)


@staff_required
def upload_supplier_price_matrix_preview(request):
    """POST multipart: file → parsed rows with product mapping suggestions."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)
    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'ok': False, 'error': 'No file provided'}, status=400)

    try:
        rows, parse_error = parse_supplier_price_matrix_file(file)
        if parse_error is not None:
            return JsonResponse({'ok': False, 'error': parse_error}, status=400)
        if not rows:
            return JsonResponse({'ok': False, 'error': 'No price rows found in file.'}, status=400)

        is_pdf = (file.name or '').lower().endswith('.pdf')
        match_cache: dict[tuple[str, str], tuple] = {}
        preview_rows = []
        for r in rows:
            match_name = r.get('match_name') or r.get('medication') or ''
            sku = (r.get('sku') or '').strip()
            cache_key = (sku.lower(), match_name.strip().lower())
            if cache_key not in match_cache:
                match_cache[cache_key] = _resolve_product_by_sku_or_name(
                    sku or None,
                    match_name,
                    allow_fuzzy=not is_pdf,
                )
            product, match_type = match_cache[cache_key]
            preview_rows.append({
                **r,
                'product_id': product.id if product else None,
                'product_name': product.name if product else None,
                'product_sku': product.sku if product else None,
                'match_type': match_type,
                'new_product_name': match_name if match_type == 'new' else None,
                'new_product_sku': sku or None if match_type == 'new' else None,
            })

        return JsonResponse({
            'ok': True,
            'rows': preview_rows,
            'source_filename': file.name,
        }, encoder=DjangoJSONEncoder)
    except Exception as exc:
        logger.exception('upload_supplier_price_matrix_preview failed')
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


def _supplier_catalog_product_ids(supplier_id: int) -> set[int]:
    """Distinct catalog product IDs linked via M2M or price matrix entries."""
    ids = set(
        Product.objects.filter(suppliers__id=supplier_id).values_list('pk', flat=True)
    )
    ids.update(
        SupplierPriceMatrixEntry.objects.filter(
            supplier_id=supplier_id,
            product_id__isnull=False,
        ).values_list('product_id', flat=True)
    )
    return ids


def _supplier_settings_rows() -> list[dict]:
    from collections import defaultdict

    m2m_by_supplier: dict[int, set[int]] = defaultdict(set)
    for supplier_id, product_id in Product.suppliers.through.objects.values_list(
        'supplier_id', 'product_id'
    ):
        m2m_by_supplier[supplier_id].add(product_id)

    matrix_by_supplier: dict[int, set[int]] = defaultdict(set)
    for supplier_id, product_id in SupplierPriceMatrixEntry.objects.filter(
        product_id__isnull=False,
    ).values_list('supplier_id', 'product_id'):
        matrix_by_supplier[supplier_id].add(product_id)

    rows: list[dict] = []
    for supplier in Supplier.objects.order_by('name'):
        product_ids = m2m_by_supplier[supplier.pk] | matrix_by_supplier[supplier.pk]
        rows.append({
            'id': supplier.pk,
            'name': supplier.name,
            'code': supplier.code or '',
            'product_count': len(product_ids),
        })
    return rows


@staff_required
def api_list_suppliers_matrix_settings(request):
    """GET: suppliers with catalog product counts for matrix settings modal."""
    if request.method != 'GET' or not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)
    return JsonResponse({'suppliers': _supplier_settings_rows()})


@staff_required
def api_delete_supplier(request, supplier_id):
    """POST: delete a supplier with no linked catalog products (superuser only)."""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

    supplier = get_object_or_404(Supplier, pk=supplier_id)
    if _supplier_catalog_product_ids(supplier.pk):
        return JsonResponse(
            {
                'success': False,
                'error': 'Cannot delete a supplier that still has linked products.',
            },
            status=400,
        )

    name = supplier.name
    supplier.delete()
    return JsonResponse({'success': True, 'id': supplier_id, 'name': name})


@staff_required
def api_create_supplier(request):
    """POST JSON: { name, code? } — create a supplier for price matrix / catalog use."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Supplier name is required.'}, status=400)

    code = (data.get('code') or '').strip() or None
    if Supplier.objects.filter(name__iexact=name).exists():
        existing = Supplier.objects.filter(name__iexact=name).first()
        return JsonResponse({
            'success': True,
            'id': existing.pk,
            'name': existing.name,
            'existing': True,
        })

    try:
        supplier = Supplier.objects.create(name=name, code=code)
    except IntegrityError:
        return JsonResponse({'success': False, 'error': 'A supplier with that name or code already exists.'}, status=400)

    return JsonResponse({'success': True, 'id': supplier.pk, 'name': supplier.name, 'existing': False})


def _matrix_myr_to_original(myr_price, currency: str, conversion_rate) -> Decimal | None:
    """Convert stored MYR tier price back to the uploaded list currency."""
    cur = (currency or 'MYR').upper()
    if cur == 'MYR' or not myr_price or not conversion_rate:
        return None
    try:
        rate = Decimal(str(conversion_rate))
        if rate <= 0:
            return None
        return (Decimal(str(myr_price)) / rate).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _matrix_conversion_rate(currency: str, rate_usd, rate_eur):
    cur = (currency or 'MYR').upper()
    if cur == 'USD':
        return rate_usd
    if cur == 'EUR':
        return rate_eur
    return None


def _matrix_price_to_myr(amount, currency: str, rate_usd, rate_eur) -> Decimal:
    cur = (currency or 'MYR').upper()
    if cur == 'MYR':
        return amount
    if cur == 'USD':
        return (amount * rate_usd).quantize(Decimal('0.01'))
    if cur == 'EUR':
        return (amount * rate_eur).quantize(Decimal('0.01'))
    return amount


@staff_required
def upload_supplier_price_matrix_confirm(request):
    """
    POST JSON: supplier_id, currency?, rate_usd?, rate_eur?, source_filename?, rows[].
    Upserts centralized supplier price matrix entries and tier prices (stored in MYR).
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    supplier_id = data.get('supplier_id')
    rows = data.get('rows') or []
    if not supplier_id:
        return JsonResponse({'success': False, 'error': 'supplier_id is required.'}, status=400)
    if not rows:
        return JsonResponse({'success': False, 'error': 'No rows provided.'}, status=400)

    supplier = get_object_or_404(Supplier, pk=supplier_id)
    source_filename = (data.get('source_filename') or '')[:255]
    currency = (data.get('currency') or 'MYR').upper()
    if currency not in ('MYR', 'USD', 'EUR'):
        return JsonResponse({'success': False, 'error': 'Invalid currency.'}, status=400)
    try:
        rate_usd = Decimal(str(data.get('rate_usd') or '4.2'))
        rate_eur = Decimal(str(data.get('rate_eur') or '4.9'))
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid exchange rate.'}, status=400)
    if currency == 'USD' and rate_usd <= 0:
        return JsonResponse({'success': False, 'error': 'USD rate must be greater than zero.'}, status=400)
    if currency == 'EUR' and rate_eur <= 0:
        return JsonResponse({'success': False, 'error': 'EUR rate must be greater than zero.'}, status=400)

    conversion_rate = _matrix_conversion_rate(currency, rate_usd, rate_eur)

    errors = []
    affected_product_ids = set()

    try:
        with transaction.atomic():
            for i, row in enumerate(rows):
                medication = (row.get('medication') or row.get('line_medication') or '').strip()
                if not medication:
                    errors.append(f"Row {i + 1}: medication name is required.")
                    continue
                strength = (row.get('strength') or '').strip()
                size = (row.get('size') or '').strip()
                form = (row.get('form') or '').strip()
                notes = (row.get('notes') or '').strip()
                tiers = row.get('tiers') or []
                if not tiers:
                    errors.append(f"Row {i + 1}: at least one price tier is required.")
                    continue

                product = None
                product_id = row.get('product_id')
                new_name = (row.get('new_product_name') or '').strip()
                new_sku = (row.get('new_product_sku') or '').strip() or None
                if product_id:
                    try:
                        product = Product.objects.get(pk=product_id)
                    except Product.DoesNotExist:
                        errors.append(f"Row {i + 1}: product not found.")
                        continue
                elif new_name:
                    product = Product.objects.filter(name__iexact=new_name).first()
                    if not product:
                        sku_to_use = new_sku if new_sku and not Product.objects.filter(sku=new_sku).exists() else None
                        product = Product.objects.create(name=new_name, description='', sku=sku_to_use)
                    elif new_sku and not product.sku and not Product.objects.filter(sku=new_sku).exclude(pk=product.pk).exists():
                        product.sku = new_sku
                        product.save(update_fields=['sku'])

                entry, _created = SupplierPriceMatrixEntry.objects.update_or_create(
                    supplier=supplier,
                    line_medication=medication,
                    strength=strength,
                    size=size,
                    defaults={
                        'form': form,
                        'notes': notes,
                        'product': product,
                        'price_currency': currency,
                        'conversion_rate': conversion_rate,
                        'source_filename': source_filename,
                    },
                )
                entry.tiers.all().delete()
                for tier in tiers:
                    try:
                        min_qty = int(tier.get('min_quantity', 1))
                        max_qty = tier.get('max_quantity')
                        max_qty = int(max_qty) if max_qty not in (None, '') else None
                        raw_price = Decimal(str(tier.get('unit_price')))
                        unit_price = _matrix_price_to_myr(raw_price, currency, rate_usd, rate_eur)
                    except (ValueError, TypeError, InvalidOperation):
                        errors.append(f"Row {i + 1}: invalid tier data.")
                        continue
                    if min_qty < 1 or unit_price < 0:
                        errors.append(f"Row {i + 1}: tier min quantity must be ≥ 1 and price ≥ 0.")
                        continue
                    SupplierPriceMatrixTier.objects.create(
                        entry=entry,
                        min_quantity=min_qty,
                        max_quantity=max_qty,
                        unit_price=unit_price,
                    )

                snapshot_tiers = _normalize_matrix_tiers_for_json(entry.tiers.all())
                SupplierPriceMatrixUploadRecord.objects.create(
                    entry=entry,
                    source_filename=source_filename,
                    price_currency=currency,
                    conversion_rate=conversion_rate,
                    tiers=snapshot_tiers,
                )

                if product:
                    if not product.suppliers.filter(pk=supplier.pk).exists():
                        product.suppliers.add(supplier)
                    affected_product_ids.add(product.id)

    except Exception as exc:
        logger.exception("upload_supplier_price_matrix_confirm failed")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    sync_saved_base_costs_for_products(list(affected_product_ids))
    return JsonResponse({
        'success': True,
        'message': f"Updated {len(rows)} price row(s) for {supplier.name}.",
        'updated_rows': len(rows),
    })
