# distributorplatform/app/order/signals.py
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import OrderItem
from commission.models import CommissionLedger
from decimal import Decimal

# Configure logger
logger = logging.getLogger(__name__)

@receiver(post_save, sender=OrderItem)
def create_commission_on_sale(sender, instance, created, **kwargs):
    """
    When a new OrderItem is created, calculate and create its commission record.
    """
    if not created:
        return # Only run on creation

    order_item = instance
    buyer = order_item.order.agent

    logger.info(f"[Commission Signal] Processing Item ID: {order_item.id} | Product: {order_item.product.name} | Buyer: {buyer.username}")

    # 1. Determine who SHOULD receive the commission
    commission_recipient = None

    # Check if the buyer is the Agent themselves (Self-Order / Restock)
    # We define "Is Agent" as belonging to a group with > 0% commission
    buyer_group = buyer.user_groups.first()
    buyer_is_agent = buyer_group and buyer_group.commission_percentage > 0

    if buyer_is_agent:
        logger.info(f"[Commission Signal] Buyer {buyer.username} is an Agent (Group: {buyer_group.name}, {buyer_group.commission_percentage}%). Assigning Self-Commission.")
        commission_recipient = buyer
    elif buyer.assigned_agent:
        logger.info(f"[Commission Signal] Buyer {buyer.username} is a Customer. Assigned Agent is {buyer.assigned_agent.username}.")
        commission_recipient = buyer.assigned_agent
    else:
        logger.warning(f"[Commission Signal] Buyer {buyer.username} is a Customer but has NO Assigned Agent. No commission will be generated.")
        return

    # 2. Get the Recipient's Commission Rules
    recipient_group = commission_recipient.user_groups.first()

    if not recipient_group:
        logger.error(f"[Commission Signal] Recipient {commission_recipient.username} has NO User Group assigned. Aborting.")
        return

    logger.info(f"[Commission Signal] Recipient: {commission_recipient.username} | Group: {recipient_group.name} | Rate: {recipient_group.commission_percentage}%")

    if recipient_group.commission_percentage <= 0:
        logger.info(f"[Commission Signal] Commission rate is 0%. No commission generated.")
        return

    # 3. Calculate Commission
    # Ensure profit is calculated (it should be set in OrderItem.save(), but good to check)
    if order_item.profit is None:
        order_item.profit = (order_item.selling_price - order_item.landed_cost) * order_item.quantity

    commission_rate = recipient_group.commission_percentage / Decimal('100.00')
    commission_amount = order_item.profit * commission_rate

    logger.info(f"[Commission Signal] Profit: {order_item.profit} | Calculated Commission: {commission_amount}")

    # 4. Create Ledger Entry
    if commission_amount > 0:
        try:
            CommissionLedger.objects.create(
                agent=commission_recipient,
                order_item=order_item,
                amount=commission_amount,
                status=CommissionLedger.CommissionStatus.PENDING
            )
            logger.info(f"[Commission Signal] SUCCESS: Created commission of {commission_amount} for {commission_recipient.username}.")
        except Exception as e:
            logger.error(f"[Commission Signal] FAILED to create ledger entry: {e}")
    else:
        logger.info(f"[Commission Signal] Commission amount is 0 or negative. Skipped.")
