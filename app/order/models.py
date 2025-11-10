# distributorplatform/app/order/models.py
from django.db import models
from django.conf import settings
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from decimal import Decimal

from product.models import Product

class Order(models.Model):
    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    # Link to the agent who placed the order
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders'
    )
    # You could add another FK to a 'Customer' if agents are selling to others

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
        # This assumes a single commission rate for the whole order,
        # based on the agent's *primary* group.
        # A more complex system might store commission per-item.
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

    def save(self, *args, **kwargs):
        # Calculate profit before saving
        self.profit = (self.selling_price - self.landed_cost) * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.id}"
