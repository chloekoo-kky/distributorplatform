# distributorplatform/app/commission/models.py
from django.db import models
from django.conf import settings
from decimal import Decimal

from order.models import Order, OrderItem

class CommissionLedger(models.Model):
    class CommissionStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'     # Earned but not yet paid
        PAID = 'PAID', 'Paid'           # Paid out to the agent
        CANCELLED = 'CANCELLED', 'Cancelled' # e.g., if the order was returned

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='commissions'
    )
    # Link to the specific item that generated the commission
    order_item = models.OneToOneField(
        OrderItem,
        on_delete=models.PROTECT,
        related_name='commission_record'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=CommissionStatus.choices, default=CommissionStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Commission of {self.amount} for {self.agent.username} on OrderItem {self.order_item.id}"
