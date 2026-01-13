import string
import random
from django.db import models
from django.conf import settings
from django.db.models import Sum, F
from decimal import Decimal

from product.models import Product

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
        CANCELLED = 'CANCELLED', 'Cancelled'

    # --- CHANGED: Use CharField with custom generator for ID ---
    id = models.CharField(
        primary_key=True,
        default=generate_order_id,
        max_length=8,
        editable=False
    )

    # Link to the agent who placed the order
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders'
    )

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
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per unit at time of sale.")
    landed_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Landed cost per unit at time of sale.")

    # --- Calculated Profit ---
    profit = models.DecimalField(
        max_digits=10, decimal_places=2,
        editable=False,
        help_text="Total profit for this line item (selling_price - landed_cost) * quantity"
    )

    @property
    def total_price(self):
        """Calculates total selling price for this line item."""
        return self.selling_price * self.quantity

    def save(self, *args, **kwargs):
        # Calculate profit before saving
        self.profit = (self.selling_price - self.landed_cost) * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.id}"
