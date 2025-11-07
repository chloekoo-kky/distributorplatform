# distributorplatform/app/sales/models.py
from django.db import models
from django.utils import timezone
from django.db.models import Sum, F, DecimalField
from decimal import Decimal
import uuid

# Import related models from other apps
from inventory.models import Quotation, Supplier, InventoryBatch
from product.models import Product
from user.models import CustomUser # Assuming you might link invoices to users later

def generate_invoice_id():
    today = timezone.now().date()
    prefix = f"INV-{today.strftime('%y%m')}-"
    suffix = uuid.uuid4().hex[:4].upper()
    return prefix + suffix

class Invoice(models.Model):
    class InvoiceStatus(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        PAID = 'PAID', 'Paid'
        PARTIALLY_RECEIVED = 'PARTIALLY_RECEIVED', 'Partially Received'
        FULLY_RECEIVED = 'FULLY_RECEIVED', 'Fully Received'
        CANCELLED = 'CANCELLED', 'Cancelled'

    invoice_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True, # Auto-generated
        help_text="Unique ID for the invoice (e.g., INV-YYMM-XXXX)."
    )
    quotation = models.OneToOneField(
        Quotation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='invoices'
    )
    date_issued = models.DateField(default=timezone.now)
    payment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when the invoice was paid."
    )
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT
    )
    notes = models.TextField(blank=True)
    transportation_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def subtotal(self):
        """Calculates the total value of all items BEFORE transport."""
        result = self.items.aggregate(total=Sum(F('quantity') * F('unit_price')))
        return result['total'] or Decimal('0.00')

    @property
    def total_amount(self):
        """Calculates the final total amount including transport."""
        sub = self.subtotal or Decimal('0.00')
        transport = self.transportation_cost or Decimal('0.00')
        return sub + transport

    def update_receive_status(self):
        """ Checks items and updates invoice status to Partially/Fully Received. """
        items = self.items.all()
        if not items: # No items, shouldn't really happen if created from quotation
            return

        total_items = items.count()
        fully_received_items = 0
        partially_received_items = 0

        for item in items:
            if item.is_fully_received:
                fully_received_items += 1
            elif item.quantity_received > 0:
                partially_received_items += 1

        new_status = self.status # Keep current status by default

        # Only update receiving status if it's currently Draft, Sent, or Paid
        # Avoid overriding Cancelled status, for example.
        relevant_statuses = [self.InvoiceStatus.DRAFT, self.InvoiceStatus.SENT, self.InvoiceStatus.PAID, self.InvoiceStatus.PARTIALLY_RECEIVED]

        if self.status in relevant_statuses:
            if fully_received_items == total_items:
                new_status = self.InvoiceStatus.FULLY_RECEIVED
            elif fully_received_items > 0 or partially_received_items > 0:
                new_status = self.InvoiceStatus.PARTIALLY_RECEIVED
            # else: remains DRAFT/SENT/PAID

            if new_status != self.status:
                self.status = new_status
                self.save(update_fields=['status', 'updated_at'])

    def save(self, *args, **kwargs):
        if not self.invoice_id:
            self.invoice_id = generate_invoice_id()
            while Invoice.objects.filter(invoice_id=self.invoice_id).exists():
                 self.invoice_id = generate_invoice_id()
        # Automatically set payment_date if status is PAID and date isn't set
        if self.status == self.InvoiceStatus.PAID and not self.payment_date:
            self.payment_date = timezone.now().date()
        # Clear payment_date if status is changed from PAID
        elif self.status != self.InvoiceStatus.PAID:
             self.payment_date = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice {self.invoice_id} for {self.supplier.name}"

class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='invoice_items'
    )
    description = models.CharField(max_length=255, blank=True, help_text="Defaults to product name, can be overridden.")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per unit at the time of invoicing.")
    quantity_received = models.PositiveIntegerField(default=0, help_text="Total quantity received across all batches for this item.")

    @property
    def total_price(self):
        """Calculates the total price for this line item."""
        if self.quantity is not None and self.unit_price is not None:
            return Decimal(self.quantity) * self.unit_price
        return Decimal('0.00')

    @property
    def is_fully_received(self):
        """ Checks if the full quantity for this item has been received. """
        return self.quantity_received >= self.quantity

    @property
    def quantity_remaining(self):
        """ Calculates the quantity yet to be received for this item. """
        return self.quantity - self.quantity_received

    def update_received_quantity(self):
        """ Recalculates quantity_received based on linked InventoryBatches. """
        # We need a way to link batches back to the specific InvoiceItem.
        # Let's add an FK from InventoryBatch to InvoiceItem.
        total_received = InventoryBatch.objects.filter(invoice_item=self).aggregate(total=Sum('quantity'))['total'] or 0
        if self.quantity_received != total_received:
            self.quantity_received = total_received
            self.save(update_fields=['quantity_received'])
            # Trigger invoice status update after item update
            self.invoice.update_receive_status()

    def save(self, *args, **kwargs):
        if not self.description and self.product:
            self.description = self.product.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.description or self.product.name} in {self.invoice.invoice_id}"
