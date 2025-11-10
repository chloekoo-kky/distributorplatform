from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import OrderItem
from commission.models import CommissionLedger # Import from your new app
from decimal import Decimal

@receiver(post_save, sender=OrderItem)
def create_commission_on_sale(sender, instance, created, **kwargs):
    """
    When a new OrderItem is created, calculate and create its commission record.
    """
    if not created:
        return # Only run on creation

    order_item = instance
    agent = order_item.order.agent

    # Get the agent's group
    agent_group = agent.user_groups.first()
    if not agent_group or agent_group.commission_percentage <= 0:
        return # No commission for this agent

    # Calculate commission
    commission_rate = agent_group.commission_percentage / Decimal('100.00')
    commission_amount = order_item.profit * commission_rate

    # Create the ledger entry
    if commission_amount > 0:
        CommissionLedger.objects.create(
            agent=agent,
            order_item=order_item,
            amount=commission_amount,
            status=CommissionLedger.CommissionStatus.PENDING
        )
