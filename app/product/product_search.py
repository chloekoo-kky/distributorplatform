"""Flexible product-name search for the manage products list."""
from __future__ import annotations

import re

from django.db.models import Func, Q, TextField, Value
from django.db.models.functions import Lower


class RegexpReplace(Func):
    function = 'REGEXP_REPLACE'
    arity = 4


def compact_product_search_text(value: str) -> str:
    """Lowercase, drop symbols and spaces, and treat 100iu / 100 unit as 100u."""
    text = re.sub(r'[^a-z0-9]+', '', (value or '').lower())
    text = re.sub(r'([0-9])units', r'\1u', text)
    text = re.sub(r'([0-9])unit', r'\1u', text)
    text = re.sub(r'([0-9])iu', r'\1u', text)
    return text


def _compact_field_expr(field_name: str):
    compacted = RegexpReplace(
        Lower(field_name),
        Value(r'[^a-z0-9]+'),
        Value(''),
        Value('g'),
        output_field=TextField(),
    )
    without_units = RegexpReplace(
        compacted,
        Value(r'([0-9])units'),
        Value(r'\1u'),
        Value('g'),
        output_field=TextField(),
    )
    without_unit = RegexpReplace(
        without_units,
        Value(r'([0-9])unit'),
        Value(r'\1u'),
        Value('g'),
        output_field=TextField(),
    )
    return RegexpReplace(
        without_unit,
        Value(r'([0-9])iu'),
        Value(r'\1u'),
        Value('g'),
        output_field=TextField(),
    )


def filter_products_by_search(queryset, search_query: str, *, include_description: bool = False):
    """Match name, alias, invoice alias, or SKU. Names ignore spaces, symbols, and iu/u dosage spelling."""
    query = (search_query or '').strip()
    if not query:
        return queryset
    needle = compact_product_search_text(query)
    direct = (
        Q(name__icontains=query)
        | Q(sku__icontains=query)
        | Q(alias_name__icontains=query)
        | Q(invoice_name_aliases__name__icontains=query)
    )
    annotations = {
        '_name_compact': _compact_field_expr('name'),
        '_alias_compact': _compact_field_expr('alias_name'),
        '_invoice_alias_compact': _compact_field_expr('invoice_name_aliases__name'),
    }
    flexible = (
        Q(_name_compact__contains=needle)
        | Q(_alias_compact__contains=needle)
        | Q(_invoice_alias_compact__contains=needle)
    )
    if include_description:
        direct |= Q(description__icontains=query)
        annotations['_description_compact'] = _compact_field_expr('description')
        flexible |= Q(_description_compact__contains=needle)
    if not needle:
        return queryset.filter(direct).distinct()
    return queryset.annotate(**annotations).filter(direct | flexible).distinct()


def compact_fields_q(query: str, fields: list[str], prefix: str) -> tuple[dict, Q]:
    """Annotations plus a Q that matches any field, ignoring spaces, symbols, and iu/u."""
    needle = compact_product_search_text(query)
    annotations = {}
    matched = Q()
    for index, field in enumerate(fields):
        matched |= Q(**{f'{field}__icontains': query})
        if needle:
            annotation = f'_{prefix}_{index}'
            annotations[annotation] = _compact_field_expr(field)
            matched |= Q(**{f'{annotation}__contains': needle})
    return annotations, matched


def product_name_search_q(search_query: str, relation: str = '') -> Q:
    """Match a Product, or a related product, with the same name rules."""
    from product.models import Product

    matched = filter_products_by_search(Product.objects.all(), search_query).values('pk')
    lookup = f'{relation}__in' if relation else 'pk__in'
    return Q(**{lookup: matched})
