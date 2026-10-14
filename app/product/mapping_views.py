"""Staff APIs for invoice description → catalog product mappings."""
from __future__ import annotations

import json
import logging
import os
import tempfile

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from tablib import Dataset

from product.invoice_sku import (
    apply_invoice_name_mappings,
    build_invoice_mapping_preview,
    dataset_is_invoice_item_sheet,
    extract_invoice_item_rows,
    parse_money,
)
from product.models import Product, ProductInvoiceNameAlias
from product.name_aliases import normalize_invoice_product_name, upsert_invoice_name_alias
from product.product_search import filter_products_by_search
from product.views import staff_required

logger = logging.getLogger(__name__)


def _price_text(value) -> str:
    if value is None:
        return ''
    return f'{value:.2f}'


def _product_mapping_payload(product: Product) -> dict:
    return {
        'id': product.pk,
        'name': product.name,
        'sku': product.sku or '',
        'reference_price': _price_text(product.reference_price),
        'aliases': [
            {
                'id': alias.pk,
                'name': alias.name,
                'source': alias.source,
            }
            for alias in product.invoice_name_aliases.all()
        ],
    }


def _alias_payload(alias: ProductInvoiceNameAlias) -> dict:
    product = alias.product
    return {
        'id': alias.pk,
        'name': alias.name,
        'source': alias.source,
        'product_id': product.pk,
        'product_name': product.name,
        'product_sku': product.sku or '',
    }


def _read_json(request):
    try:
        data = json.loads(request.body or b'{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@staff_required
def api_product_aliases(request):
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    if request.method == 'GET':
        search = (request.GET.get('search') or '').strip()
        try:
            page_number = int(request.GET.get('page') or 1)
        except (TypeError, ValueError):
            page_number = 1
        queryset = Product.objects.prefetch_related(
            Prefetch(
                'invoice_name_aliases',
                queryset=ProductInvoiceNameAlias.objects.order_by('name'),
            )
        ).order_by('name')
        if search:
            queryset = filter_products_by_search(queryset, search)
        paginator = Paginator(queryset, 50)
        try:
            page = paginator.page(page_number)
        except EmptyPage:
            page = paginator.page(paginator.num_pages or 1) if paginator.num_pages else None
        items = [_product_mapping_payload(product) for product in (page.object_list if page else [])]
        return JsonResponse({
            'success': True,
            'items': items,
            'pagination': {
                'current_page': page.number if page else 1,
                'total_pages': paginator.num_pages,
                'total_count': paginator.count,
                'has_next': page.has_next() if page else False,
                'has_previous': page.has_previous() if page else False,
            },
        })

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    data = _read_json(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    return _save_alias(data)


@staff_required
@require_POST
def api_product_alias_detail(request, alias_id):
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    alias = ProductInvoiceNameAlias.objects.select_related('product').filter(pk=alias_id).first()
    if alias is None:
        return JsonResponse({'success': False, 'error': 'Mapping not found.'}, status=404)

    data = _read_json(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

    if data.get('delete'):
        alias.delete()
        return JsonResponse({'success': True})

    return _save_alias(data, existing=alias)


@staff_required
@require_POST
def api_product_reference_price(request, product_id):
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return JsonResponse({'success': False, 'error': 'Product not found.'}, status=404)

    data = _read_json(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

    raw = data.get('reference_price')
    if raw is None or str(raw).strip() == '':
        product.reference_price = None
    else:
        amount = parse_money(raw)
        if amount is None:
            return JsonResponse({'success': False, 'error': 'Enter a reference price like 120.00.'}, status=400)
        product.reference_price = amount
    product.save(update_fields=['reference_price'])
    return JsonResponse({'success': True, 'reference_price': _price_text(product.reference_price)})


def _save_alias(data: dict, existing: ProductInvoiceNameAlias | None = None):
    name = (data.get('name') or '').strip()[:200]
    normalized = normalize_invoice_product_name(name)
    if not normalized:
        return JsonResponse({'success': False, 'error': 'Alias name is required.'}, status=400)

    try:
        product_id = int(data.get('product_id'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Choose a product.'}, status=400)

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return JsonResponse({'success': False, 'error': 'Product not found.'}, status=404)

    if normalize_invoice_product_name(product.name) == normalized:
        return JsonResponse({
            'success': False,
            'error': "That name is already this product's catalog name, so it does not need a mapping.",
        }, status=400)

    other = ProductInvoiceNameAlias.objects.filter(name_normalized=normalized)
    if existing is not None:
        other = other.exclude(pk=existing.pk)
    taken = other.select_related('product').first()
    if taken is not None and taken.product_id != product.pk:
        return JsonResponse({
            'success': False,
            'error': f'That alias is already mapped to {taken.product.name}.',
        }, status=400)
    if taken is not None and existing is None:
        taken.product = product
        taken.name = name
        taken.source = ProductInvoiceNameAlias.SOURCE_MANUAL
        taken.save()
        return JsonResponse({'success': True, 'item': _alias_payload(taken)})

    if existing is None:
        alias = upsert_invoice_name_alias(
            product,
            name,
            source=ProductInvoiceNameAlias.SOURCE_MANUAL,
        )
        if alias is None:
            return JsonResponse({
                'success': False,
                'error': "That name is already this product's catalog name, so it does not need a mapping.",
            }, status=400)
        return JsonResponse({'success': True, 'item': _alias_payload(alias)})

    existing.product = product
    existing.name = name
    existing.source = ProductInvoiceNameAlias.SOURCE_MANUAL
    existing.save()
    return JsonResponse({'success': True, 'item': _alias_payload(existing)})


def _load_import_dataset(path: str, filename: str):
    dataset = Dataset()
    if filename.endswith('.csv') or path.endswith('.csv'):
        with open(path, 'rb') as handle:
            raw = handle.read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
        dataset.load(text, format='csv')
    else:
        with open(path, 'rb') as handle:
            dataset.load(handle.read(), format='xlsx')
    return dataset


def _mapping_import_message(result: dict) -> str:
    parts = []
    if result['created']:
        parts.append(f"Created {result['created']} mapping(s).")
    if result['updated']:
        parts.append(f"Updated {result['updated']} mapping(s).")
    if result.get('prices'):
        parts.append(f"Updated reference price on {result['prices']} product(s).")
    if result['skipped'] and not parts:
        parts.append('Those rows already match the selected products.')
    return ' '.join(parts) or 'Nothing was saved.'


@staff_required
def api_import_invoice_mappings(request):
    """Preview or save product-name mappings from an invoice item list."""
    if request.method != 'POST' or request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    confirm = (request.POST.get('confirm') or '').lower() == 'true'
    if confirm:
        temp_path = request.POST.get('temp_file_path') or ''
        if not temp_path or not os.path.exists(temp_path):
            return JsonResponse({'success': False, 'error': 'Upload the invoice again.'}, status=400)
        try:
            assignments = json.loads(request.POST.get('assignments') or '[]')
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({'success': False, 'error': 'Invalid mapping selections.'}, status=400)
        if not isinstance(assignments, list) or not assignments:
            return JsonResponse({'success': False, 'error': 'Choose at least one product to map.'}, status=400)
        try:
            dataset = _load_import_dataset(temp_path, temp_path)
            rows = extract_invoice_item_rows(dataset, require_item_code=False)
            result = apply_invoice_name_mappings(rows, assignments)
        except Exception as exc:
            logger.exception('Invoice mapping import failed')
            return JsonResponse({'success': False, 'error': str(exc)}, status=500)
        if result['errors']:
            return JsonResponse({'success': False, 'error': ' '.join(result['errors'][:8])}, status=400)
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return JsonResponse({'success': True, 'message': _mapping_import_message(result), **result})

    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'success': False, 'error': 'No file uploaded.'}, status=400)
    filename = upload.name or ''
    if not filename.lower().endswith(('.csv', '.xls', '.xlsx')):
        return JsonResponse({'success': False, 'error': 'Upload a .csv or .xlsx invoice.'}, status=400)

    suffix = os.path.splitext(filename)[1] or '.xlsx'
    fd, temp_path = tempfile.mkstemp(prefix='mapping_import_', suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        dataset = _load_import_dataset(temp_path, filename)
    except Exception as exc:
        logger.exception('Could not read invoice for mapping import')
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return JsonResponse({'success': False, 'error': f'Could not read the file: {exc}'}, status=400)

    if not dataset_is_invoice_item_sheet(dataset):
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return JsonResponse({
            'success': False,
            'error': 'Use a file with Code, Item Code, or SKU, plus a Description or a price column.',
        }, status=400)

    rows = extract_invoice_item_rows(dataset, require_item_code=False)
    if not rows:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return JsonResponse({
            'success': False,
            'error': 'No product rows were found in that file.',
        }, status=400)

    preview = build_invoice_mapping_preview(rows)
    return JsonResponse({
        'success': True,
        'temp_file_path': temp_path,
        'total_rows': len(preview),
        'rows': preview,
    })
