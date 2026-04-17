import string
import random
from django.db import models
from django.conf import settings
from django.db.models import Sum, F
from decimal import Decimal

from product.models import Product


class Customer(models.Model):
    """
    Central customer record for manual orders. Admins manage this list;
    salesteam can pick an existing customer or create a new one when entering orders.
    """
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name or f"Customer #{self.pk}"


class SalesInvoiceIssuer(models.Model):
    """
    Legal / billing identity used on customer-facing sales invoices (orders).
    Staff can maintain several issuers (e.g. different entities or bank accounts).
    """
    label = models.CharField(
        max_length=120,
        help_text='Short name shown in dropdowns (e.g. "HQ — ABC Sdn Bhd").',
    )
    legal_name = models.CharField(max_length=255, help_text='Full name as printed on the invoice.')
    address = models.TextField(blank=True, help_text='Registered / mailing address.')
    phone = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    tax_id = models.CharField(
        max_length=80,
        blank=True,
        help_text='SST / VAT / tax registration number, if applicable.',
    )
    registration_no = models.CharField(
        max_length=80,
        blank=True,
        help_text='Company registration number, if applicable.',
    )
    bank_details = models.TextField(
        blank=True,
        help_text='Payment instructions (bank name, account no., reference).',
    )
    logo = models.ImageField(
        upload_to='invoice_issuers/logos/%Y/%m/',
        blank=True,
        null=True,
        help_text='Shown top-left on printed sales invoices (PNG, JPG, or WebP).',
    )
    is_default = models.BooleanField(
        default=False,
        help_text='Pre-selected when opening the sales invoice dialog.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'label']

    def __str__(self):
        return self.label or self.legal_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            SalesInvoiceIssuer.objects.exclude(pk=self.pk).update(is_default=False)


class CustomerAddress(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='addresses'
    )
    label = models.CharField(max_length=100, blank=True, null=True, help_text='Optional label, e.g. Home, Office.')
    address = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'created_at']

    def __str__(self):
        label = self.label or 'Address'
        return f"{label} for {self.customer.name or self.customer_id}"


def generate_order_id():
    """Generates a random 8-character alphanumeric ID."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choices(characters, k=8))

class Order(models.Model):
    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        TO_PAY = 'TO_PAY', 'To Pay'
        TO_SHIP = 'TO_SHIP', 'To Ship'
        TO_RECEIVE = 'TO_RECEIVE', 'To Receive'
        COMPLETED = 'COMPLETED', 'Completed'
        CLOSED = 'CLOSED', 'Closed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class SalesChannel(models.TextChoices):
        WHATSAPP = 'WhatsApp', 'WhatsApp'
        SHOPEE = 'Shopee', 'Shopee'
        LAZADA = 'Lazada', 'Lazada'
        Website = 'Website', 'Website'
        OTHER = 'Other', 'Other'

    # --- CHANGED: Use CharField with custom generator for ID ---
    id = models.CharField(
        primary_key=True,
        default=generate_order_id,
        max_length=8,
        editable=False
    )

    # Link to the agent who placed the order (for manual orders, this is the salesperson)
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders'
    )

    # Manual order entry: who created the order (salesperson). If set, no commission is generated.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_created',
        help_text='Staff/salesperson who entered this order. When set, commission is skipped.'
    )

    # Sales channel for manual orders (e.g. WhatsApp, Shopee, Website)
    sales_channel = models.CharField(
        max_length=50,
        choices=SalesChannel.choices,
        default=SalesChannel.OTHER,
        blank=True
    )

    # Optional link to central Customer record (manual orders)
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text='Linked customer from central list (manual orders).'
    )

    # Guest customer details (snapshot for display/export; also used when no customer linked)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    shipping_address = models.TextField(blank=True, null=True)

    # Optional remarks for manual orders (e.g. platform order ID)
    remarks = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Optional remarks for this order (e.g. external platform order ID).",
    )

    # Transaction date for manual orders (e.g. date of sale on platform)
    transaction_date = models.DateField(blank=True, null=True, help_text='Date of transaction (manual orders).')

    payment_method = models.CharField(max_length=50, blank=True, null=True, help_text="The selected payment method (e.g., COD).")
    
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.id} by {self.agent.username}"

    @property
    def total_profit(self):
        """Calculates the total profit for all items in this order."""
        aggregation = self.items.aggregate(
            total_profit=Sum(F('profit'))
        )
        return aggregation['total_profit'] or Decimal('0.00')

    @property
    def total_commission(self):
        """Calculates the total commission earned on this order."""
        user_group = self.agent.user_groups.first()
        if not user_group or user_group.commission_percentage == 0:
            return Decimal('0.00')

        commission_rate = user_group.commission_percentage / Decimal('100.00')
        return self.total_profit * commission_rate

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)

    # --- Snapshots at time of sale ---
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Unit price at time of sale; for manual orders equals actual_unit_price.")
    landed_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Landed cost per unit at time of sale.")

    # --- Manual orders: platform vs net price ---
    platform_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Original price on platform (for record-keeping)."
    )
    actual_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Net amount received after platform fees; used for order total."
    )

    # --- Calculated Profit ---
    profit = models.DecimalField(
        max_digits=10, decimal_places=2,
        editable=False,
        help_text="(effective_unit_price - landed_cost) * quantity"
    )

    @property
    def effective_unit_price(self):
        """Price used for totals: actual_unit_price if set (manual orders), else selling_price."""
        if self.actual_unit_price is not None:
            return self.actual_unit_price
        return self.selling_price

    @property
    def total_price(self):
        """Order total for this line: based on effective_unit_price (actual received for manual orders)."""
        return self.effective_unit_price * self.quantity

    def save(self, *args, **kwargs):
        unit = self.effective_unit_price
        self.profit = (unit - self.landed_cost) * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.id}"
