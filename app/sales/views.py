# distributorplatform/app/sales/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage
import json

from inventory.models import Quotation, QuotationItem
from .models import Invoice, InvoiceItem
from .forms import InvoiceUpdateForm

from inventory.views import staff_required

@staff_required
def api_manage_invoices(request):
    """
    JSON API to fetch filtered and paginated invoices.
    Supports Month/Year filtering with '0' as All Time (Reset).
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    # --- 1. Get Params ---
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    page_number = request.GET.get('page', 1)

    # Date Filter (0 means All Time)
    try:
        month = int(request.GET.get('month', 0))
        year = int(request.GET.get('year', 0))
    except ValueError:
        month = 0
        year = 0

    # --- 2. Build Queryset ---
    # Prefetch items and related products for the nested table
    queryset = Invoice.objects.select_related('supplier', 'quotation').prefetch_related(
        'items__product'
    ).order_by('-date_issued', '-created_at')

    # --- 3. Apply Filters ---

    # Date Filter (date_issued) - Only apply if specific month is requested
    if month and year:
        queryset = queryset.filter(date_issued__year=year, date_issued__month=month)

    # Search Filter
    if search_query:
        queryset = queryset.filter(
            Q(invoice_id__icontains=search_query) |
            Q(supplier__name__icontains=search_query)
        )

    # Status Filter
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # --- 4. Pagination ---
    paginator = Paginator(queryset, 20)  # 20 items per page
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        return JsonResponse({'items': [], 'pagination': {}})

    # --- 5. Serialize ---
    serialized_items = []
    for invoice in page_obj.object_list:

        # Serialize nested invoice items
        items_data = []
        for item in invoice.items.all():
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
                'is_fully_received': item.is_fully_received,
                # Fields needed for "Receive Stock" modal
                'product_id': item.product.id if item.product else None,
            })

        serialized_items.append({
            'invoice_id': invoice.invoice_id,
            'supplier_name': invoice.supplier.name,
            'supplier_id': invoice.supplier.id,
            'quotation_id': invoice.quotation.quotation_id if invoice.quotation else None,
            'quotation_pk': invoice.quotation.id if invoice.quotation else None,
            'date_issued': invoice.date_issued.strftime('%Y-%m-%d'),
            'payment_date': invoice.payment_date.strftime('%Y-%m-%d') if invoice.payment_date else '-',
            'status': invoice.get_status_display(),
            'status_code': invoice.status,
            'transportation_cost': float(invoice.transportation_cost),
            'total_amount': float(invoice.total_amount),
            'items': items_data
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
@transaction.atomic
def create_invoice_from_quotation(request, quotation_id):
    """ Creates an Invoice and InvoiceItems based on a given Quotation. """
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('core:manage_dashboard')

    quotation = get_object_or_404(Quotation.objects.prefetch_related('items__product'), quotation_id=quotation_id)

    if hasattr(quotation, 'invoice') and quotation.invoice:
        messages.warning(request, f"Invoice {quotation.invoice.invoice_id} already exists for this quotation.")
        return redirect('inventory:quotation_detail', quotation_id=quotation.quotation_id)

    if not quotation.items.exists():
        messages.error(request, "Cannot create an invoice from a quotation with no items.")
        return redirect('inventory:quotation_detail', quotation_id=quotation.quotation_id)

    try:
        invoice = Invoice.objects.create(
            quotation=quotation,
            supplier=quotation.supplier,
            date_issued=timezone.now().date(),
            status=Invoice.InvoiceStatus.DRAFT,
            notes=quotation.notes,
            transportation_cost=quotation.transportation_cost or Decimal('0.00')
        )

        invoice_items_to_create = []
        for item in quotation.items.all():
            invoice_items_to_create.append(
                InvoiceItem(
                    invoice=invoice,
                    product=item.product,
                    description=item.product.name,
                    quantity=item.quantity,
                    unit_price=item.quoted_price
                )
            )
        InvoiceItem.objects.bulk_create(invoice_items_to_create)

        messages.success(request, f"Successfully created Invoice {invoice.invoice_id} from Quotation {quotation.quotation_id}.")
        return redirect('inventory:quotation_detail', quotation_id=quotation.quotation_id)

    except IntegrityError as e:
        messages.error(request, f"Database error creating invoice: {e}")
    except Exception as e:
        messages.error(request, f"An unexpected error occurred: {e}")

    return redirect('inventory:quotation_detail', quotation_id=quotation.quotation_id)


@staff_required
def edit_invoice(request, invoice_id):
    """
    Handles fetching invoice data (GET for modal population)
    and updating invoice data (POST from modal form).
    """
    invoice = get_object_or_404(Invoice, invoice_id=invoice_id)

    if request.method == 'POST':
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
             messages.error(request, "Invalid request type.")
             return redirect('core:manage_dashboard')

        form = InvoiceUpdateForm(request.POST, instance=invoice)
        if form.is_valid():
            try:
                form.save()
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'errors': {'__all__': [str(e)]}}, status=500)
        else:
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)

    elif request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        data = {
            'invoice_id': invoice.invoice_id,
            'status': invoice.status,
            'payment_date': invoice.payment_date.strftime('%Y-%m-%d') if invoice.payment_date else '',
            'notes': invoice.notes,
            'update_url': reverse('sales:edit_invoice', kwargs={'invoice_id': invoice.invoice_id})
        }
        return JsonResponse(data)

    messages.error(request, "Invalid request.")
    return redirect('core:manage_dashboard')
