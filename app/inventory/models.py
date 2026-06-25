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
        supplier_name = self.supplier.name if getattr(self, "supplier", None) else "Unknown supplier"
        return f"Quotation {self.quotation_id} from {supplier_name}"

class QuotationItem(models.Model):
    INPUT_CURRENCY_EUR = 'EUR'
    INPUT_CURRENCY_USD = 'USD'
    INPUT_CURRENCY_MYR = 'MYR'
    INPUT_CURRENCY_CHOICES = [
        (INPUT_CURRENCY_EUR, 'EUR'),
        (INPUT_CURRENCY_USD, 'USD'),
        (INPUT_CURRENCY_MYR, 'MYR'),
    ]

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE)
    line_product_label = models.CharField(
        max_length=255,
        blank=True,
        help_text='Name as shown on the supplier quotation or import file; may differ from the mapped catalog product name.',
    )
    quantity = models.PositiveIntegerField(
        default=0,
        help_text="Order quantity; 0 means the supplier lists this price but no order is placed on this quotation.",
    )
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per single unit in MYR")
    # When set, rate changes only affect MYR (quoted_price); EUR/USD display stays fixed from input_value.
    input_currency = models.CharField(
        max_length=3,
        choices=INPUT_CURRENCY_CHOICES,
        null=True,
        blank=True,
        help_text="Currency the user entered (EUR/USD/MYR). When rate changes, only MYR is recalculated."
    )
    input_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price in input_currency. Used to recompute quoted_price (MYR) when rate changes."
    )

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


class SupplierPriceMatrixEntry(models.Model):
    """
    One supplier catalog row (medication + strength + size) from a price list upload.
    Maps to a catalog Product when matched; holds tiered unit prices on related tiers.
    """
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name='price_matrix_entries',
    )
    product = models.ForeignKey(
        'product.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_price_matrix_entries',
    )
    line_medication = models.CharField(
        max_length=255,
        help_text="Medication / product name as shown on the supplier price list.",
    )
    strength = models.CharField(max_length=255, blank=True)
    form = models.CharField(max_length=50, blank=True, help_text="e.g. INJ")
    size = models.CharField(max_length=100, blank=True, help_text="e.g. 1 mL")
    notes = models.TextField(blank=True)
    price_currency = models.CharField(
        max_length=3,
        choices=[('MYR', 'MYR'), ('USD', 'USD'), ('EUR', 'EUR')],
        default='MYR',
        help_text="Currency of the uploaded price list (stored tiers are normalized to MYR).",
    )
    conversion_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Exchange rate used on last upload (1 unit of price_currency → MYR).",
    )
    effective_date = models.DateField(null=True, blank=True)
    source_filename = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['line_medication', 'strength', 'size']
        constraints = [
            models.UniqueConstraint(
                fields=['supplier', 'line_medication', 'strength', 'size'],
                name='uniq_supplier_matrix_line',
            ),
        ]
        verbose_name = 'Supplier price matrix entry'
        verbose_name_plural = 'Supplier price matrix entries'

    def __str__(self):
        parts = [self.line_medication]
        if self.strength:
            parts.append(self.strength)
        if self.size:
            parts.append(self.size)
        return f"{self.supplier.name}: {' / '.join(parts)}"


class SupplierPriceMatrixTier(models.Model):
    """Volume-based unit price for a matrix entry (e.g. 1–999, 1000–1999, 2000+)."""
    entry = models.ForeignKey(
        SupplierPriceMatrixEntry,
        on_delete=models.CASCADE,
        related_name='tiers',
    )
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Null means open-ended (e.g. 2000+).",
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['min_quantity']
        constraints = [
            models.UniqueConstraint(
                fields=['entry', 'min_quantity'],
                name='uniq_matrix_entry_tier_min_qty',
            ),
        ]

    def __str__(self):
        upper = f"{self.max_quantity}" if self.max_quantity else "+"
        return f"{self.min_quantity}–{upper} @ RM {self.unit_price}"


class SupplierPriceMatrixUploadRecord(models.Model):
    """Snapshot of tier prices after each price-list upload for one matrix entry."""
    entry = models.ForeignKey(
        SupplierPriceMatrixEntry,
        on_delete=models.CASCADE,
        related_name='upload_records',
    )
    source_filename = models.CharField(max_length=255, blank=True)
    price_currency = models.CharField(max_length=3, default='MYR')
    conversion_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Exchange rate used for this upload (1 unit of price_currency → MYR).",
    )
    tiers = models.JSONField(
        default=list,
        help_text="Tier prices (MYR) after this upload: [{min_quantity, max_quantity, unit_price}, …]",
    )
    effective_date = models.DateField(
        null=True,
        blank=True,
        help_text="Business date for this price (e.g. invoice date from payable invoice import).",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_date', '-uploaded_at']
        verbose_name = 'Supplier price matrix upload record'
        verbose_name_plural = 'Supplier price matrix upload records'

    def __str__(self):
        return f"{self.entry} @ {self.uploaded_at:%Y-%m-%d %H:%M}"


class InventoryBatch(models.Model):
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE, related_name='batches')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    batch_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Optional lot/batch identifier. Can be set later when splitting a receipt.",
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
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The quotation this batch is based on (optional when receiving directly from an invoice)."
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
        label = self.batch_number or f'#{self.pk}'
        return f"Batch {label} for {self.product.name}"

