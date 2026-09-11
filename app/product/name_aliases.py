"""Invoice description → master product aliases (kept when products are merged)."""
from __future__ import annotations

from product.models import ProductInvoiceNameAlias


def normalize_invoice_product_name(name: str | None) -> str:
    return ProductInvoiceNameAlias.normalize_name(name)


def upsert_invoice_name_alias(product, raw_name: str | None, *, source: str = ProductInvoiceNameAlias.SOURCE_MERGE):
    """Attach an invoice/merged name to a master product. No-op if it matches the catalog name."""
    trimmed = (raw_name or '').strip()[:200]
    normalized = normalize_invoice_product_name(trimmed)
    if not normalized or not product:
        return None
    if normalize_invoice_product_name(getattr(product, 'name', '')) == normalized:
        return None

    existing = ProductInvoiceNameAlias.objects.filter(name_normalized=normalized).first()
    if existing:
        existing.product = product
        existing.name = trimmed
        existing.source = source
        existing.save()
        return existing

    return ProductInvoiceNameAlias.objects.create(
        product=product,
        name=trimmed,
        name_normalized=normalized,
        source=source,
    )


def record_merged_product_invoice_names(primary, secondaries) -> None:
    """Keep deleted product names (and their aliases) as lookups on the master."""
    names: list[str] = []
    for secondary in secondaries:
        names.append(secondary.name)
        alias_name = getattr(secondary, 'alias_name', None)
        if alias_name:
            names.append(alias_name)
        for alias in list(secondary.invoice_name_aliases.all()):
            names.append(alias.name)
            alias.delete()
    for name in names:
        upsert_invoice_name_alias(primary, name, source=ProductInvoiceNameAlias.SOURCE_MERGE)


def resolve_imported_invoice_product(product_model, *, description: str, item_code: str = ''):
    """
    Match an invoice line to a product: SKU, catalog name, then invoice-name alias.
    Creates a product from the description when nothing matches.
    Returns (product, created).
    """
    item_code = (item_code or '').strip()
    desc = (description or '').strip()
    if item_code:
        product = product_model.objects.filter(sku__iexact=item_code).first()
        if product:
            return product, False
    if not desc:
        return None, False

    product = product_model.objects.filter(name__iexact=desc).first()
    if product:
        return product, False

    alias = ProductInvoiceNameAlias.objects.filter(
        name_normalized=normalize_invoice_product_name(desc),
    ).select_related('product').first()
    if alias:
        return alias.product, False

    name = desc[:200]
    product, created = product_model.objects.get_or_create(
        name=name,
        defaults={'description': 'Auto-imported from payable invoice'},
    )
    return product, created
