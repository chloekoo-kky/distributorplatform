# distributorplatform/app/inventory/models.py
from django.db import models
from django.db.models import Sum, F
import uuid
from decimal import Decimal
from django.utils import timezone


class Supplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text="A unique code for this supplier (e.g., 'SUP001')."
    )
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name


def generate_quotation_id():
    from datetime import date
    today = date.today()
    prefix = f"QTN-{today.strftime('%y%m')}-"
    suffix = uuid.uuid4().hex[:4].upper()
    return prefix + suffix

class Quotation(models.Model):
    quotation_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True, # Allow blank initially
        help_text="Unique ID for the quotation (e.g., QTN-YYMM-XXXX). Auto-generated if left blank."
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='quotations')
    date_quoted = models.DateField()
    transportation_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Total transportation cost for this entire quotation."
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if not self.quotation_id:
            self.quotation_id = generate_quotation_id()
            while Quotation.objects.filter(quotation_id=self.quotation_id).exists():
                 self.quotation_id = generate_quotation_id()
        super().save(*args, **kwargs)

    @property
    def item_count(self):
        """Calculates the number of distinct items in the quotation."""
        # Check if items have been prefetched
        if hasattr(self, '_prefetched_objects_cache') and 'items' in self._prefetched_objects_cache:
            return len(self._prefetched_objects_cache['items'])
        return self.items.count()

    @property
    def total_value(self):
        """Calculates the total value of ALL ITEMS in the quotation (pre-transport)."""
        # Check if items have been prefetched and calculate locally if possible
        if hasattr(self, '_prefetched_objects_cache') and 'items' in self._prefetched_objects_cache:
            return sum(item.total_item_price for item in self._prefetched_objects_cache['items'])
        # Otherwise, query the database
        result = self.items.aggregate(total=Sum(F('quantity') * F('quoted_price')))
        return result['total'] or Decimal('0.00')

    @property
    def total_landed_cost(self):
        """Calculates the total landed cost (items + transport)."""
        total_val = self.total_value or Decimal('0.00')
        transport_cost = self.transportation_cost or Decimal('0.00')
        return total_val + transport_cost

    # --- UPDATED STATUS PROPERTY ---
    @property
    def status(self):
        """
        Returns the status of the quotation based on invoice existence.
        Relies on 'invoice' being prefetched in the view for efficiency.
        """
        # Check if the related 'invoice' object exists (was loaded by prefetch_related)
        # and is not None. Using hasattr avoids an error if 'invoice' wasn't prefetched.
        if hasattr(self, 'invoice') and self.invoice is not None:
            return "Invoiced"
        return "Open"
    # --- END UPDATED PROPERTY ---

    def __str__(self):
        return f"Quotation {self.quotation_id} from {self.supplier.name}"

class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per single unit for this item")

    @property
    def total_item_price(self):
        """Calculates the total price for this line item (quantity * price)."""
        if self.quantity is not None and self.quoted_price is not None:
            return Decimal(self.quantity) * self.quoted_price
        return Decimal('0.00')

    @property
    def landed_cost_per_unit(self):
        """
        Calculates the landed cost per unit for this item,
        distributing the quotation's transport cost pro-rata by value.
        """
        if self.quantity is None or self.quantity == 0 or self.quoted_price is None:
            return self.quoted_price or None

        quotation_total_item_value = self.quotation.total_value

        if quotation_total_item_value is None or quotation_total_item_value == 0:
            return self.quoted_price

        item_total_price = self.total_item_price

        # Ensure Decimal division
        item_share_of_value = item_total_price / quotation_total_item_value

        # Ensure Decimal multiplication
        item_share_of_transport = (self.quotation.transportation_cost or Decimal('0.00')) * item_share_of_value

        item_total_landed_cost = item_total_price + item_share_of_transport

        return item_total_landed_cost / Decimal(self.quantity)

    @property
    def transport_cost_per_unit(self):
        """
        Calculates the share of transportation cost for a single unit of this item.
        """
        if self.quantity is None or self.quantity == 0 or self.quoted_price is None:
            return Decimal('0.00')

        quotation_total_item_value = self.quotation.total_value

        if quotation_total_item_value is None or quotation_total_item_value == 0:
            return Decimal('0.00') # No transport cost if no item value

        item_total_price = self.total_item_price

        # Ensure Decimal division
        item_share_of_value = item_total_price / quotation_total_item_value

        # Ensure Decimal multiplication
        item_share_of_transport = (self.quotation.transportation_cost or Decimal('0.00')) * item_share_of_value

        # Return the per-unit share of transport cost
        return item_share_of_transport / Decimal(self.quantity)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ ${self.quoted_price} in {self.quotation.quotation_id}"


class InventoryBatch(models.Model):
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE, related_name='batches')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    batch_number = models.CharField(
        max_length=100,
        help_text="A number for this batch, e.g., PO-123. Can be duplicated across different products/deliveries."
    )
    quantity = models.PositiveIntegerField(help_text="The actual quantity received.")
    received_date = models.DateField()
    expiry_date = models.DateField( # <-- ADD THIS FIELD
        null=True,
        blank=True,
        help_text="Optional: Expiry date for this batch."
    )
    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        help_text="The quotation this batch is based on."
    )
    invoice_item = models.ForeignKey(
        'sales.InvoiceItem',
        on_delete=models.SET_NULL, # Or PROTECT? Decide based on business logic
        null=True,
        blank=True, # Allow batches not linked to an invoice item?
        related_name='received_batches',
        help_text="The specific invoice item this batch fulfills."
    )

    class Meta:
        verbose_name_plural = "Inventory Batches"

    def __str__(self):
        return f"Batch {self.batch_number} for {self.product.name}"

