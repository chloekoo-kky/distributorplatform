"""Match an invoice item list (Item Code + Description) to catalog products and set SKU."""
from __future__ import annotations

import re

from django.db import transaction

from product.models import Product, ProductInvoiceNameAlias
from product.name_aliases import normalize_invoice_product_name, upsert_invoice_name_alias

ITEM_CODE_HEADERS = frozenset({
    'item code', 'itemcode', 'item_code', 'sku', 'code', 'product code',
})
DESCRIPTION_HEADERS = frozenset({'description', 'item description', 'product description'})
PRICE_HEADER_PRIORITY = (
    'reference price',
    'ref price',
    'unit price (ex) (myr)',
    'unit price (ex)',
    'unit price',
    'price',
)


def normalize_header(value) -> str:
    return ' '.join(str(value or '').replace('\xa0', ' ').strip().lower().split())


def normalize_item_code(value) -> str:
    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return ''
        if value.is_integer():
            return str(int(value))
        text = str(value).strip()
    else:
        text = str(value).strip()
    if re.fullmatch(r'\d+\.0+', text):
        return text.split('.', 1)[0]
    return text


def parse_money(value):
    """Return a 2-decimal amount, or None when the cell is blank."""
    from decimal import Decimal, InvalidOperation

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        amount = Decimal(str(value))
    else:
        text = str(value).strip().replace(',', '')
        text = re.sub(r'[^\d.\-]', '', text)
        if text in ('', '-', '.', '-.'):
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None
    if amount < 0:
        return None
    return amount.quantize(Decimal('0.01'))


def _price_column_index(headers: list[str]) -> int | None:
    for name in PRICE_HEADER_PRIORITY:
        if name in headers:
            return headers.index(name)
    return None


def clean_description(value) -> str:
    text = str(value or '').replace('\xa0', ' ').replace('\r', ' ').replace('\n', ' ')
    return ' '.join(text.split()).strip()


def sheet_rows_from_dataset(dataset) -> list[list]:
    header = ['' if cell is None else cell for cell in (dataset.headers or [])]
    body = []
    for row in dataset:
        body.append(list(row))
    return [header] + body


def _header_column_indexes(row: list) -> tuple[int | None, int | None, int | None] | None:
    normalized = [normalize_header(cell) for cell in row]
    # A catalog export has both sku and name. Leave that for the product importer.
    if 'sku' in normalized and 'name' in normalized:
        return None
    code_idx = next((i for i, header in enumerate(normalized) if header in ITEM_CODE_HEADERS), None)
    desc_idx = next((i for i, header in enumerate(normalized) if header in DESCRIPTION_HEADERS), None)
    price_idx = _price_column_index(normalized)
    if code_idx is not None and desc_idx is not None:
        return code_idx, desc_idx, price_idx
    if code_idx is not None and price_idx is not None:
        return code_idx, None, price_idx
    return None


def dataset_is_invoice_item_sheet(dataset) -> bool:
    for row in sheet_rows_from_dataset(dataset):
        if _header_column_indexes(row):
            return True
    return False


def extract_invoice_item_rows(dataset, *, require_item_code: bool = True) -> list[dict]:
    """One row per description. Repeated lines with the same code collapse."""
    rows = sheet_rows_from_dataset(dataset)
    header_at = None
    columns = None
    for index, row in enumerate(rows):
        columns = _header_column_indexes(row)
        if columns:
            header_at = index
            break
    if header_at is None or columns is None:
        return []

    code_idx, desc_idx, price_idx = columns
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for row in rows[header_at + 1:]:
        code = normalize_item_code(row[code_idx] if code_idx is not None and code_idx < len(row) else None)
        description = clean_description(row[desc_idx] if desc_idx is not None and desc_idx < len(row) else None)[:200]
        price = parse_money(row[price_idx] if price_idx is not None and price_idx < len(row) else None)
        if require_item_code:
            if not code or not description:
                continue
        elif not description and not code:
            continue
        key = normalize_invoice_product_name(description) if description else f'sku:{code.lower()}'
        if not key:
            continue
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                'row_key': key,
                'description': description,
                'codes': set(),
                'reference_price': None,
            }
            grouped[key] = bucket
            order.append(key)
        if code:
            bucket['codes'].add(code)
        if price is not None and bucket['reference_price'] is None:
            bucket['reference_price'] = f'{price:.2f}'

    extracted = []
    for key in order:
        bucket = grouped[key]
        codes = sorted(bucket['codes'])
        extracted.append({
            'row_key': key,
            'description': bucket['description'],
            'item_code': codes[0] if len(codes) == 1 else '',
            'item_codes': codes,
            'reference_price': bucket['reference_price'] or '',
        })
    return extracted


def _preview_row(source: dict, **extra) -> dict:
    row = {
        'row_key': source['row_key'],
        'description': source['description'],
        'item_code': source.get('item_code') or '',
        'product_id': None,
        'product_name': '',
        'current_sku': '',
        'reference_price': source.get('reference_price') or '',
        'current_reference_price': '',
        'status': 'unmatched',
        'message': '',
    }
    row.update(extra)
    return row


def build_invoice_sku_preview(extracted_rows: list[dict]) -> list[dict]:
    products = list(Product.objects.all().only('id', 'name', 'alias_name', 'sku'))
    by_name: dict[str, Product] = {}
    by_alias_name: dict[str, Product] = {}
    by_sku: dict[str, Product] = {}
    for product in products:
        by_name.setdefault(normalize_invoice_product_name(product.name), product)
        if product.alias_name:
            by_alias_name.setdefault(normalize_invoice_product_name(product.alias_name), product)
        if product.sku:
            by_sku[product.sku.strip().lower()] = product

    alias_map = {
        alias.name_normalized: alias.product
        for alias in ProductInvoiceNameAlias.objects.select_related('product')
    }

    preview: list[dict] = []
    for source in extracted_rows:
        codes = source.get('item_codes') or []
        if len(codes) != 1:
            joined = ', '.join(codes)
            preview.append(_preview_row(
                source,
                status='conflict',
                message=f'This description has more than one item code ({joined}).',
            ))
            continue

        code = codes[0]
        key = source['row_key']
        product = alias_map.get(key) or by_name.get(key) or by_alias_name.get(key)
        if product is None:
            preview.append(_preview_row(
                source,
                item_code=code,
                status='unmatched',
                message='No product matches this description. Choose one to save the mapping and set the SKU.',
            ))
            continue

        owner = by_sku.get(code.lower())
        if owner is not None and owner.pk != product.pk:
            preview.append(_preview_row(
                source,
                item_code=code,
                product_id=product.pk,
                product_name=product.name,
                current_sku=product.sku or '',
                status='conflict',
                message=f'Item code {code} is already the SKU for {owner.name}.',
            ))
            continue

        same_sku = (product.sku or '').strip().lower() == code.lower()
        preview.append(_preview_row(
            source,
            item_code=code,
            product_id=product.pk,
            product_name=product.name,
            current_sku=product.sku or '',
            status='unchanged' if same_sku else 'update',
        ))

    _flag_shared_targets(preview)
    return preview


def _flag_shared_targets(preview: list[dict]) -> None:
    """One item code and one product can only be used once in the file."""
    codes: dict[str, list[dict]] = {}
    products: dict[int, list[dict]] = {}
    for row in preview:
        if row['status'] == 'conflict' or not row.get('item_code'):
            continue
        codes.setdefault(row['item_code'].lower(), []).append(row)
        if row.get('product_id'):
            products.setdefault(row['product_id'], []).append(row)

    for group in codes.values():
        product_ids = {row['product_id'] for row in group if row.get('product_id')}
        if len(product_ids) < 2:
            continue
        for row in group:
            row['status'] = 'conflict'
            row['message'] = f"Item code {row['item_code']} matches more than one product."

    for group in products.values():
        distinct_codes = {row['item_code'].lower() for row in group if row.get('item_code')}
        if len(distinct_codes) < 2:
            continue
        for row in group:
            row['status'] = 'conflict'
            row['message'] = f"{row['product_name']} would receive more than one item code."


def apply_invoice_sku_assignments(extracted_rows: list[dict], assignments: list[dict]) -> dict:
    """
    Set SKU from item code and store the invoice description as a product alias
    when it is not already the catalog name.
    """
    by_key = {row['row_key']: row for row in extracted_rows}
    prepared: list[tuple[dict, Product]] = []
    errors: list[str] = []
    seen_codes: dict[str, int] = {}
    seen_products: dict[int, str] = {}

    for assignment in assignments:
        row_key = str(assignment.get('row_key') or '')
        source = by_key.get(row_key)
        try:
            product_id = int(assignment.get('product_id'))
        except (TypeError, ValueError):
            continue
        if source is None or not source.get('item_code'):
            continue
        code = source['item_code'][:100]
        code_key = code.lower()
        if code_key in seen_codes and seen_codes[code_key] != product_id:
            errors.append(f'Item code {code} is assigned to more than one product.')
            continue
        if product_id in seen_products and seen_products[product_id].lower() != code_key:
            errors.append(f'A product was assigned more than one item code ({seen_products[product_id]} and {code}).')
            continue
        seen_codes[code_key] = product_id
        seen_products[product_id] = code
        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            errors.append(f'Product for "{source["description"]}" was not found.')
            continue
        owner = Product.objects.filter(sku__iexact=code).exclude(pk=product.pk).first()
        if owner is not None:
            errors.append(f'Item code {code} is already the SKU for {owner.name}.')
            continue
        prepared.append((source, product))

    if errors:
        return {'updated': 0, 'aliases': 0, 'errors': errors}

    updated = 0
    aliases = 0
    with transaction.atomic():
        for source, product in prepared:
            code = source['item_code'][:100]
            if (product.sku or '').strip().lower() != code.lower():
                product.sku = code
                product.save(update_fields=['sku'])
                updated += 1
            alias = upsert_invoice_name_alias(
                product,
                source['description'],
                source=ProductInvoiceNameAlias.SOURCE_INVOICE,
            )
            if alias is not None:
                aliases += 1

    return {'updated': updated, 'aliases': aliases, 'errors': []}


def build_invoice_mapping_preview(extracted_rows: list[dict]) -> list[dict]:
    """Match invoice descriptions to existing aliases or catalog names. Does not change SKUs."""
    products = list(Product.objects.all().only('id', 'name', 'alias_name', 'sku', 'reference_price'))
    by_name: dict[str, Product] = {}
    by_alias_name: dict[str, Product] = {}
    by_sku: dict[str, Product] = {}
    for product in products:
        by_name.setdefault(normalize_invoice_product_name(product.name), product)
        if product.alias_name:
            by_alias_name.setdefault(normalize_invoice_product_name(product.alias_name), product)
        if product.sku:
            by_sku.setdefault(product.sku.strip().lower(), product)

    alias_map = {
        alias.name_normalized: alias.product
        for alias in ProductInvoiceNameAlias.objects.select_related('product')
    }

    preview: list[dict] = []
    for source in extracted_rows:
        codes = source.get('item_codes') or []
        item_code = codes[0] if len(codes) == 1 else ', '.join(codes)
        key = source['row_key']
        alias_product = alias_map.get(key)
        name_product = by_name.get(key)
        suggested = by_alias_name.get(key)
        if alias_product is not None:
            product = alias_product
            status = 'mapped'
        elif name_product is not None:
            product = name_product
            status = 'catalog'
        elif suggested is not None:
            product = suggested
            status = 'suggested'
        else:
            product = None
            status = 'unmatched'
        if product is None and len(codes) == 1:
            sku_product = by_sku.get(codes[0].strip().lower())
            if sku_product is not None:
                product = sku_product
                description = source.get('description') or ''
                if not description or normalize_invoice_product_name(description) == normalize_invoice_product_name(product.name):
                    status = 'catalog'
                else:
                    status = 'suggested'
        current_price = ''
        if product is not None and product.reference_price is not None:
            current_price = f'{product.reference_price:.2f}'
        preview.append({
            'row_key': key,
            'description': source['description'],
            'item_code': item_code,
            'status': status,
            'product_id': product.pk if product else None,
            'product_name': product.name if product else '',
            'product_sku': (product.sku or '') if product else '',
            'reference_price': source.get('reference_price') or '',
            'current_reference_price': current_price,
        })
    return preview


def apply_invoice_name_mappings(extracted_rows: list[dict], assignments: list[dict]) -> dict:
    """Create or update invoice description → product aliases, and optional reference prices. Does not change SKUs."""
    by_key = {row['row_key']: row for row in extracted_rows}
    created = 0
    updated = 0
    skipped = 0
    prices = 0
    errors: list[str] = []
    prepared: list[tuple] = []

    for assignment in assignments:
        row_key = str(assignment.get('row_key') or '')
        source = by_key.get(row_key)
        try:
            product_id = int(assignment.get('product_id'))
        except (TypeError, ValueError):
            continue
        if source is None:
            continue
        product = Product.objects.filter(pk=product_id).first()
        label = source.get('description') or source.get('item_code') or row_key
        if product is None:
            errors.append(f'Product for "{label}" was not found.')
            continue

        price = None
        raw_price = assignment.get('reference_price')
        if 'reference_price' in assignment and str(raw_price or '').strip() != '':
            price = parse_money(raw_price)
            if price is None:
                errors.append(f'Reference price for "{label}" is not a valid amount.')
                continue

        description = (source.get('description') or '').strip()
        write_alias = bool(description) and (
            normalize_invoice_product_name(product.name) != normalize_invoice_product_name(description)
        )
        existing = None
        if write_alias:
            existing = ProductInvoiceNameAlias.objects.filter(
                name_normalized=normalize_invoice_product_name(description)
            ).first()
            if existing is not None and existing.product_id == product.pk:
                write_alias = False
        price_change = price is not None and product.reference_price != price
        if not write_alias and not price_change:
            skipped += 1
            continue
        prepared.append((source, product, existing, price if price_change else None, write_alias))

    if errors:
        return {'created': 0, 'updated': 0, 'skipped': skipped, 'prices': 0, 'errors': errors}

    with transaction.atomic():
        for source, product, existing, price, write_alias in prepared:
            if write_alias:
                alias = upsert_invoice_name_alias(
                    product,
                    source['description'],
                    source=ProductInvoiceNameAlias.SOURCE_INVOICE,
                )
                if alias is None:
                    skipped += 1
                elif existing is None:
                    created += 1
                else:
                    updated += 1
            if price is not None:
                product.reference_price = price
                product.save(update_fields=['reference_price'])
                prices += 1

    return {'created': created, 'updated': updated, 'skipped': skipped, 'prices': prices, 'errors': []}
