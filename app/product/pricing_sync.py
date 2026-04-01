# Keep Product.saved_base_cost aligned with quotation landed costs.
from __future__ import annotations

from decimal import Decimal


def _as_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _latest_quotation_item_for_product(product_pk: int):
    from inventory.models import QuotationItem

    return (
        QuotationItem.objects.filter(product_id=product_pk)
        .select_related("quotation")
        .prefetch_related("quotation__items")
        .order_by("-quotation__date_quoted", "-id")
        .first()
    )


def reconcile_saved_base_cost_with_quotations(product, supplier_costs: list[dict]) -> None:
    """
    Refresh saved_base_cost (and supplier pin) when quotation pricing changed but the
    product row still holds an old snapshot. Called when opening the pricing modal (GET).
    """
    from product.models import Product

    if not supplier_costs:
        return

    cost_rows = []
    for sc in supplier_costs:
        sid = sc.get("supplier_id")
        c = _as_decimal(sc.get("cost"))
        if sid is not None and c is not None:
            cost_rows.append({"supplier_id": int(sid), "cost": c})

    if not cost_rows:
        return

    current_costs = {r["cost"] for r in cost_rows}
    updates = {}

    sup_fk = getattr(product, "saved_base_cost_supplier_id", None)

    if sup_fk:
        match = next((r for r in cost_rows if r["supplier_id"] == sup_fk), None)
        if match is not None:
            if product.saved_base_cost != match["cost"]:
                updates["saved_base_cost"] = match["cost"]
        else:
            qi = _latest_quotation_item_for_product(product.pk)
            if qi and qi.landed_cost_per_unit is not None:
                landed = _as_decimal(qi.landed_cost_per_unit)
                updates["saved_base_cost"] = landed
                updates["saved_base_cost_supplier_id"] = qi.quotation.supplier_id
    elif product.saved_base_cost is not None:
        s = _as_decimal(product.saved_base_cost)
        if len(cost_rows) == 1:
            r0 = cost_rows[0]
            if product.saved_base_cost_supplier_id != r0["supplier_id"]:
                updates["saved_base_cost_supplier_id"] = r0["supplier_id"]
            if s != r0["cost"]:
                updates["saved_base_cost"] = r0["cost"]
        else:
            matches = [r for r in cost_rows if r["cost"] == s]
            if len(matches) == 1:
                updates["saved_base_cost_supplier_id"] = matches[0]["supplier_id"]
            elif s not in current_costs:
                qi = _latest_quotation_item_for_product(product.pk)
                if qi and qi.landed_cost_per_unit is not None:
                    landed = _as_decimal(qi.landed_cost_per_unit)
                    updates["saved_base_cost"] = landed
                    updates["saved_base_cost_supplier_id"] = qi.quotation.supplier_id

    if updates:
        Product.objects.filter(pk=product.pk).update(**updates)
        for k, v in updates.items():
            setattr(product, k, v)


def sync_saved_base_costs_for_quotation(quotation) -> None:
    """
    After quotation items or transport/date are saved (bulk_update bypasses signals).
    """
    from inventory.models import QuotationItem
    from product.models import Product

    supplier_id = quotation.supplier_id
    items = (
        QuotationItem.objects.filter(quotation_id=quotation.pk)
        .select_related("product", "quotation")
        .prefetch_related("quotation__items")
    )
    for item in items:
        product = item.product
        if getattr(product, "saved_base_cost_supplier_id", None) != supplier_id:
            continue
        landed = item.landed_cost_per_unit
        if landed is None:
            continue
        ld = _as_decimal(landed)
        if product.saved_base_cost != ld:
            Product.objects.filter(pk=product.pk).update(saved_base_cost=ld)
            product.saved_base_cost = ld
