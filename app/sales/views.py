# distributorplatform/app/sales/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from django.http import JsonResponse
import json

from inventory.models import Quotation, QuotationItem
from .models import Invoice, InvoiceItem
from .forms import InvoiceUpdateForm

from inventory.views import staff_required


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
            # --- UPDATED to use payment_date ---
            'payment_date': invoice.payment_date.strftime('%Y-%m-%d') if invoice.payment_date else '',
            'notes': invoice.notes,
            'update_url': reverse('sales:edit_invoice', kwargs={'invoice_id': invoice.invoice_id})
        }
        return JsonResponse(data)

    messages.error(request, "Invalid request.")
    return redirect('core:manage_dashboard')
