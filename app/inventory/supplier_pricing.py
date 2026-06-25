# Centralized supplier price matrix: parse uploads and resolve product costs.
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from tablib import Dataset

MEDICATION_KEYS = (
    'medication', 'product', 'product name', 'drug', 'drug name', 'item', 'item name', 'name',
)
STRENGTH_KEYS = ('strength', 'medication strength', 'dose', 'dosage')
FORM_KEYS = ('form',)
SIZE_KEYS = ('size', 'volume', 'pack size', 'pack')
NOTES_KEYS = ('notes', 'note', 'remarks', 'remark')
SKU_KEYS = ('sku', 'product sku', 'item sku')
SINGLE_PRICE_KEYS = (
    'quoted price (unit)', 'quoted price', 'unit price', 'price', 'price (unit)', 'cost',
)

TIER_HEADER_RE = re.compile(
    r'(\d+)\s*[-–—]\s*(\d+)|(\d+)\s*\+',
    re.IGNORECASE,
)


def _normalize_header(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def _get_row_value(row: dict, *keys: str) -> str:
    for key in keys:
        if key in row and row[key] not in (None, ''):
            return str(row[key]).strip()
    return ''


def _parse_tier_from_header(header: str) -> tuple[int, int | None] | None:
    cleaned = _normalize_header(header)
    cleaned = cleaned.replace(',', '').replace('scripts', '').replace('units', '').replace('qty', '').strip()
    m = re.search(r'(\d+)\s*[-–—]\s*(\d+)', cleaned)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+)\s*[-–—]\s*\+', cleaned)
    if m:
        return int(m.group(1)), None
    m = re.search(r'(\d+)\s*\+', cleaned)
    if m:
        return int(m.group(1)), None
    return None


def _parse_price(value) -> Decimal | None:
    if value is None or value == '':
        return None
    text = str(value).strip().replace(',', '').replace('$', '').replace('RM', '').strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalize_import_row(raw_row: dict) -> dict[str, str]:
    return {_normalize_header(k): (str(v).strip() if v is not None else '') for k, v in raw_row.items()}


def _composite_line_name(medication: str, strength: str, size: str) -> str:
    parts = [medication]
    if strength:
        parts.append(strength)
    if size:
        parts.append(size)
    return ' / '.join(parts)


def _row_has_matrix_header_signals(normalized_headers: list[str]) -> bool:
    has_product = any(
        h in MEDICATION_KEYS or h in SKU_KEYS
        for h in normalized_headers if h
    )
    has_price = any(
        _parse_tier_from_header(h) or h in SINGLE_PRICE_KEYS
        for h in normalized_headers if h
    )
    return has_product and has_price


def _find_matrix_header_row(table_rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(table_rows[:15]):
        normalized = [_normalize_header(cell) for cell in row]
        if _row_has_matrix_header_signals(normalized):
            return idx
    return None


def _clean_pdf_table(table: list[list]) -> list[list[str]]:
    cleaned: list[list[str]] = []
    for row in table or []:
        cells = [re.sub(r'\s+', ' ', str(cell or '').strip()) for cell in row]
        if any(cells):
            cleaned.append(cells)
    return cleaned


def _pad_row(row: list[str], width: int) -> list[str]:
    values = list(row[:width])
    if len(values) < width:
        values.extend([''] * (width - len(values)))
    return values


def _normalize_table_headers(row: list[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for idx, cell in enumerate(row):
        header = _normalize_header(cell) or f'column_{idx + 1}'
        if header in seen:
            seen[header] += 1
            header = f'{header}_{seen[header]}'
        else:
            seen[header] = 1
        headers.append(header)
    return headers


def _medication_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if h in MEDICATION_KEYS:
            return i
        if h.startswith('product name') or h == 'product':
            return i
    return None


def _detect_column_groups(header_row: list[str]) -> list[tuple[int, int]]:
    """Split a wide PDF row into side-by-side tables (e.g. duplicate Product Name columns)."""
    normalized = [_normalize_header(cell) for cell in header_row]
    product_starts = [i for i, h in enumerate(normalized) if h in MEDICATION_KEYS]
    if len(product_starts) <= 1:
        return [(0, len(header_row))]
    groups: list[tuple[int, int]] = []
    for i, start in enumerate(product_starts):
        end = product_starts[i + 1] if i + 1 < len(product_starts) else len(header_row)
        if end > start:
            groups.append((start, end))
    return groups or [(0, len(header_row))]


def _slice_table_columns(rows: list[list[str]], start: int, end: int) -> list[list[str]]:
    return [
        [row[i] if i < len(row) else '' for i in range(start, len(row))]
        for row in rows
    ]


_STRENGTH_UNIT_RE = re.compile(
    r'(?:mg|mcg|μg|ug|iu)(?:\s*/\s*m[lL])?'
    r'|\d[\d./,\s]*g\s*/\s*m[lL]',
    re.IGNORECASE,
)
_SIZE_UNIT_RE = re.compile(r'\b(ml|l|each|kit|kits|vial|vials|capsule|capsules|tablet|tablets)\b', re.IGNORECASE)
_STRENGTH_VALUE_RE = re.compile(
    r'^[\d.,/]+\s*(?:mg|mcg|μg|ug|iu)(?:\s*/\s*m[lL])?$',
    re.IGNORECASE,
)
_SIZE_VALUE_RE = re.compile(
    r'^[\d.,]+\s*(?:ml|l|each|kit|kits|vial|vials|capsule|capsules|tablet|tablets)$',
    re.IGNORECASE,
)
_STRENGTH_BODY_RE = re.compile(
    r'\d[\d./,\s]*(?:mg|mcg|μg|ug|iu)(?:\s*/\s*m[lL])?'
    r'|\d[\d./,\s]*g\s*/\s*m[lL]',
    re.IGNORECASE,
)


def _first_price_column_index(headers: list[str]) -> int:
    for i, h in enumerate(headers):
        if h and (_parse_tier_from_header(h) or h in SINGLE_PRICE_KEYS):
            return i
    return len(headers)


def _strength_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if h in STRENGTH_KEYS:
            return i
    return None


def _size_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if h in SIZE_KEYS:
            return i
    return None


def _looks_like_strength_value(text: str) -> bool:
    t = (text or '').strip()
    if not t:
        return False
    if _STRENGTH_BODY_RE.search(t):
        return True
    return bool(
        re.match(r'^[./]\d', t)
        and re.search(r'(?:mg|mcg|μg|ug|iu)\b', t, re.IGNORECASE)
    )


def _peel_compound_strength_from_name(name: str) -> tuple[str, str]:
    """Peel trailing compound-strength fragments from a product name."""
    name = (name or '').strip()
    match = re.search(r'\s+(?P<tail>(?:\d+(?:\.\d+)?/)+)\s*$', name)
    if match:
        return name[:match.start()].strip(), match.group('tail')
    match = re.search(r'\s+(?P<tail>\d+(?:\.\d+)?/\d+(?:\.\d+)?)\s*$', name)
    if match and re.search(r'[A-Za-z)]', name[:match.start()]):
        return name[:match.start()].strip(), match.group('tail')
    return name, ''


def _compound_strength_continuation_prefix(strength: str) -> str:
    """Base prefix for continuation rows, e.g. '5/1.25/0.5 mg' -> '5/1.25'."""
    strength = (strength or '').strip()
    match = re.match(
        r'^(?P<prefix>(?:\d+(?:\.\d+)?/)+)\d+(?:\.\d+)?\s*(?:mg|mcg|μg|ug|iu)\b',
        strength,
        re.IGNORECASE,
    )
    if match:
        return match.group('prefix').rstrip('/')
    match = re.match(r'^(\d+(?:\.\d+)?)/', strength)
    if match:
        return match.group(1)
    return ''


def _repair_compound_strength_continuation(strength: str, compound_prefix: str) -> str:
    strength = (strength or '').strip()
    compound_prefix = (compound_prefix or '').strip()
    if not strength or not compound_prefix:
        return strength
    if strength[0] == '.':
        return _join_strength_prefix(compound_prefix, strength)
    return strength


def _normalize_medication_slashes(text: str) -> str:
    text = re.sub(r'\s*/\s*', ' / ', (text or '').strip())
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_spaced_strength(strength: str) -> str:
    """Merge strengths split across spaces, e.g. '5 0 mg/ml' -> '50 mg/ml'."""
    strength = (strength or '').strip()
    match = re.match(r'^(\d+)\s+(0\s*mg/m[lL].*)$', strength, re.IGNORECASE)
    if match:
        return re.sub(r'\s+', ' ', f"{match.group(1)}{match.group(2)}")
    match = re.match(r'^(\d)\s+(\d\s*mg/m[lL].*)$', strength, re.IGNORECASE)
    if match:
        return re.sub(r'\s+', ' ', f"{match.group(1)}{match.group(2)}")
    match = re.match(r'^((?:\d(?:\s+\d)+))\s+(mg/m[lL].*)$', strength, re.IGNORECASE)
    if match:
        digits = re.sub(r'\s+', '', match.group(1))
        return f"{digits} {match.group(2)}"
    return strength


def _size_has_natural_number(size: str) -> bool:
    match = re.match(r'^(\d+)', (size or '').strip())
    return bool(match and int(match.group(1)) > 0)


def _peel_trailing_size_from_strength(strength: str) -> tuple[str, str]:
    """Move a trailing integer from strength into size, e.g. '200 mg/ml 1' -> '200 mg/ml', '1'."""
    strength = (strength or '').strip()
    match = re.match(
        r'^(?P<strength>.+?(?:mg|mcg|μg|ug|iu)(?:\s*/\s*m[lL])?)\s+(?P<size_num>\d+(?:\.\d+)?)\s*$',
        strength,
        re.IGNORECASE,
    )
    if match:
        return match.group('strength').strip(), match.group('size_num')
    return strength, ''


def _reconstruct_size(size_num: str, size: str) -> str:
    size_num = (size_num or '').strip()
    size = (size or '').strip()

    if _size_has_natural_number(size):
        return size

    unit = 'ml'
    unit_match = re.search(r'\b(ml|l)\b', size, re.IGNORECASE)
    if unit_match:
        unit = unit_match.group(1).lower()

    if not size_num:
        return size

    if re.match(r'^0\s*(?:ml|l)?$', size, re.IGNORECASE):
        if '.' in size_num:
            return f"{size_num} {unit}"
        return f"{size_num}0 {unit}"

    if size.lower() in ('ml', 'l', '') or not size:
        return f"{size_num} {unit}"

    return size


def _repair_strength_size_pair(strength: str, size: str) -> tuple[str, str]:
    strength = (strength or '').strip()
    size = (size or '').strip()

    unit_only = size.lower() in ('ml', 'l')
    strength_has_trailing_size = bool(re.search(
        r'(?:mg|mcg|μg|ug|iu)(?:\s*/\s*m[lL])?\s+\d',
        strength,
        re.IGNORECASE,
    ))
    if unit_only or (not size and strength_has_trailing_size):
        strength, size = _split_merged_strength_size(strength, size or 'ml')

    if not _size_has_natural_number(size):
        strength, peeled = _peel_trailing_size_from_strength(strength)
        strength = _normalize_spaced_strength(strength)
        size = _reconstruct_size(peeled, size)
    else:
        strength = _normalize_spaced_strength(strength)

    return strength.strip(), size.strip()


def _merge_product_name(base: str, suffix: str) -> str:
    base = (base or '').rstrip()
    suffix = (suffix or '').strip()
    if not suffix:
        return _repair_split_medication_words(base)
    if not base:
        return _repair_split_medication_words(suffix)
    if base.endswith('('):
        return _repair_split_medication_words(f"{base}{suffix}".strip())
    if suffix.startswith('('):
        return _repair_split_medication_words(f"{base}{suffix}".strip())
    return _repair_split_medication_words(f"{base} {suffix}".strip())


_PHARMA_FORM_WORDS = frozenset({
    'capsule', 'capsules', 'tablet', 'tablets', 'caplet', 'caplets',
    'injection', 'solution', 'suspension', 'cream', 'ointment', 'gel',
    'syrup', 'powder', 'lozenge', 'lozenges', 'spray', 'drops',
    'suppository', 'suppositories', 'emulsion', 'lotion', 'patch',
})
_SPLIT_MEDICATION_WORD_RE = re.compile(r'\b([A-Za-z]{3,})\s+([a-z]{2,6})\b')


def _repair_split_medication_words(text: str) -> str:
    """Fix PDF line-break artifacts like 'Capsu le' -> 'Capsule'."""
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if not text:
        return text
    text = re.sub(r'^\?\s*-\s*', '7-', text)
    text = re.sub(r'^\?\s*', '7', text)

    def _replace(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        combined = left + right
        if combined.lower() not in _PHARMA_FORM_WORDS:
            return match.group(0)
        if left.isupper():
            return combined.upper()
        if left[0].isupper():
            return combined[0].upper() + combined[1:].lower()
        return combined.lower()

    prev = None
    while prev != text:
        prev = text
        text = _SPLIT_MEDICATION_WORD_RE.sub(_replace, text)
    return _normalize_medication_slashes(text)


def _split_name_fragment_and_strength_prefix(text: str) -> tuple[str, str]:
    """Split 'Grapeseed Oil) 2' into name + leading strength digit(s)."""
    text = (text or '').strip()
    if not text:
        return '', ''
    match = re.match(r'^(?P<name>.+?\))\s*(?P<prefix>\d{1,3})$', text)
    if match:
        return match.group('name').strip(), match.group('prefix')
    match = re.match(r'^(?P<name>.+)\s+(?P<prefix>\d{1,3})$', text)
    if match and not _looks_like_strength_value(text):
        name = match.group('name').strip()
        if re.search(r'[a-zA-Z)]', name):
            return name, match.group('prefix')
    return text, ''


def _peel_trailing_strength_from_name(name: str) -> tuple[str, str]:
    name = (name or '').strip()
    name, compound = _peel_compound_strength_from_name(name)
    if compound:
        return name, compound
    return _split_name_fragment_and_strength_prefix(name)


def _join_strength_prefix(prefix: str, body: str) -> str:
    prefix = (prefix or '').strip()
    body = (body or '').strip()
    if not prefix:
        return _normalize_spaced_strength(body)
    if not body:
        return prefix
    if body[0] == '.':
        parts = prefix.split('/')
        if len(parts) > 1 and re.match(r'^\d+\.\d+$', parts[-1]):
            base = '/'.join(parts[:-1] + [parts[-1].split('.')[0]])
        elif len(parts) > 1:
            base = '/'.join(parts[:-1])
        else:
            base = prefix
        return _normalize_spaced_strength(f"{base}{body}")
    if body[0] == '/':
        return _normalize_spaced_strength(f"{prefix.rstrip('/')}/{body.lstrip('/')}")
    if (
        not prefix.endswith('/')
        and re.match(r'^\d+/', body)
        and '/' in prefix
    ):
        return _normalize_spaced_strength(body)
    if prefix.endswith('/'):
        return _normalize_spaced_strength(f"{prefix}{body}")
    if re.match(r'^0\s*mg', body, re.IGNORECASE):
        return _normalize_spaced_strength(f"{prefix}{body}")
    if '/' in prefix and re.match(
        r'^\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*\s*(?:mg|mcg|μg|ug|iu)\b',
        body,
        re.IGNORECASE,
    ):
        joiner = '' if prefix.endswith('/') else '/'
        return _normalize_spaced_strength(f"{prefix}{joiner}{body}")
    return _normalize_spaced_strength(f"{prefix} {body}")


def _looks_like_size_value(text: str) -> bool:
    t = (text or '').strip()
    if not t:
        return False
    if _SIZE_VALUE_RE.match(t):
        return True
    return t.lower() in ('ml', 'l', 'each')


def _looks_like_product_fragment(text: str) -> bool:
    t = (text or '').strip()
    if not t or _parse_price(t) is not None:
        return False
    if _looks_like_strength_value(t) or _looks_like_size_value(t):
        return False
    if re.match(r'^[\d.,]+$', t):
        return False
    return bool(re.search(r'[a-zA-Z)]', t))


def _consume_strength_token(tokens: list[str], start: int) -> tuple[str, int]:
    if start >= len(tokens):
        return '', 0
    t = tokens[start]
    if _looks_like_strength_value(t) and not _SIZE_VALUE_RE.match(t):
        return t, 1
    if re.match(r'^[\d./]+$', t) or re.match(r'^\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)+$', t):
        if start + 1 < len(tokens):
            nxt = tokens[start + 1].strip()
            if '/' in t:
                slash_merge = re.match(
                    r'^(\d+(?:\.\d+)?)\s*(mg|mcg|μg|ug|iu)\b',
                    nxt,
                    re.IGNORECASE,
                )
                if slash_merge:
                    merged = f"{t}/{slash_merge.group(1)} {slash_merge.group(2)}"
                    if _looks_like_strength_value(merged):
                        return merged, 2
            merged = f"{t} {nxt}".strip()
            if _looks_like_strength_value(merged):
                return merged, 2
            if re.match(r'^[\d.]+$', nxt):
                if start + 2 < len(tokens):
                    unit = tokens[start + 2].strip()
                    if re.match(r'^(?:mg|mcg|μg|ug|iu)\b', unit, re.IGNORECASE):
                        merged3 = f"{t}/{tokens[start + 1]} {unit}"
                        if _looks_like_strength_value(merged3):
                            return merged3, 3
        if start + 2 < len(tokens):
            unit = tokens[start + 1].strip()
            denom = tokens[start + 2].strip()
            if _STRENGTH_UNIT_RE.search(unit) and denom.lower() in ('ml', 'l'):
                return f"{t} {unit}/{denom}", 3
    if re.match(r'^[\d.,]+$', t):
        if start + 1 < len(tokens):
            merged = f"{t} {tokens[start + 1]}".strip()
            if _looks_like_strength_value(merged):
                return merged, 2
        if start + 2 < len(tokens):
            unit = tokens[start + 1].strip()
            denom = tokens[start + 2].strip()
            if _STRENGTH_UNIT_RE.search(unit) and denom.lower() in ('ml', 'l'):
                return f"{t} {unit}/{denom}", 3
    return '', 0


def _consume_size_token(tokens: list[str], start: int) -> tuple[str, int]:
    if start >= len(tokens):
        return '', 0
    t = tokens[start]
    if _SIZE_VALUE_RE.match(t):
        return t, 1
    if re.match(r'^[\d.,]+$', t) and start + 1 < len(tokens):
        unit = tokens[start + 1].strip()
        if unit.lower() in ('ml', 'l', 'each'):
            return f"{t} {unit}", 2
    return '', 0


def _split_merged_strength_size(strength: str, size: str) -> tuple[str, str]:
    """Fix rows where strength absorbed the size number and size is only the unit."""
    strength = _normalize_spaced_strength((strength or '').strip())
    size = (size or '').strip()
    if not strength:
        return strength, size
    if size.lower() in ('ml', 'l'):
        m = re.match(
            r'^(?P<strength>[\d.,]+\s*(?:mg|mcg|μg|ug|g|iu)\s*/?\s*m?[lL]?)\s+(?P<num>[\d.,]+)\s*$',
            strength,
            re.IGNORECASE,
        )
        if m:
            return m.group('strength').strip(), f"{m.group('num')} {size}"
    return strength, size


def _parse_strength_size_from_fragments(
    fragments: list[str],
    *,
    initial_strength_prefix: str = '',
) -> tuple[list[str], str, str]:
    tokens = [f.strip() for f in fragments if f and f.strip()]
    product_parts: list[str] = []
    strength = ''
    size = ''
    strength_prefix = (initial_strength_prefix or '').strip()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        name_part, digit_suffix = _peel_compound_strength_from_name(token)
        if not digit_suffix:
            name_part, digit_suffix = _split_name_fragment_and_strength_prefix(token)
        if digit_suffix:
            strength_prefix = (
                _join_strength_prefix(strength_prefix, digit_suffix)
                if strength_prefix else digit_suffix
            )
            token = name_part
            if not token:
                i += 1
                continue

        if not strength and token.endswith('/') and re.match(r'^[\d./]+$', token):
            strength_prefix = token
            i += 1
            continue

        if not strength and token and _looks_like_product_fragment(token):
            product_parts.append(token)
            i += 1
            continue

        if not strength:
            if strength_prefix and (
                _looks_like_strength_value(token)
                or re.match(r'^0\s*mg', token, re.IGNORECASE)
                or re.match(r'^[./]\d', token)
                or (strength_prefix.endswith('/') and re.match(r'^\d', token))
            ):
                strength = _join_strength_prefix(strength_prefix, token)
                strength_prefix = ''
                i += 1
                continue
            parsed, consumed = _consume_strength_token(tokens, i)
            if parsed:
                strength = _join_strength_prefix(strength_prefix, parsed) if strength_prefix else parsed
                strength_prefix = ''
                i += consumed
                continue

        if not size:
            parsed, consumed = _consume_size_token(tokens, i)
            if parsed:
                size = parsed
                i += consumed
                continue

        i += 1

    if not strength and strength_prefix:
        strength = strength_prefix

    strength, size = _repair_strength_size_pair(strength, size)
    return product_parts, strength, size


def _looks_like_price_cell(cell: str) -> bool:
    text = (cell or '').strip()
    if not text or _parse_price(text) is None:
        return False
    if re.search(r'[$]|RM\b', text, re.IGNORECASE):
        return True
    return bool(re.search(r'\d+\.\d{2}', text))


def _collect_row_price_values(padded: list[str], start: int) -> tuple[int | None, list[str]]:
    """Return the first price column index and consecutive price cells after it."""
    price_idx: int | None = None
    prices: list[str] = []
    for i in range(start, len(padded)):
        cell = (padded[i] or '').strip()
        if _looks_like_price_cell(cell):
            if price_idx is None:
                price_idx = i
            prices.append(cell)
        elif price_idx is not None:
            break
    return price_idx, prices


def _repair_pdf_matrix_row(
    padded: list[str],
    headers: list[str],
    *,
    compound_prefix: str = '',
) -> list[str]:
    """
    Re-align product / strength / size when pdfplumber splits cells
    (e.g. product name at '(', strength as '200' + 'mg/mL', size as '2.5' + 'mL').
    """
    med_col = _medication_column_index(headers)
    if med_col is None:
        return padded

    price_start = _first_price_column_index(headers)
    strength_col = _strength_column_index(headers)
    size_col = _size_column_index(headers)

    actual_price_start, price_values = _collect_row_price_values(padded, med_col + 1)
    if actual_price_start is not None:
        fragments_end = actual_price_start
    else:
        fragments_end = len(padded)
        for i in range(med_col + 1, len(padded)):
            if _looks_like_price_cell(padded[i]):
                fragments_end = i
                break
    fragments = padded[med_col + 1:fragments_end]

    med_text, med_prefix = _peel_trailing_strength_from_name(padded[med_col])

    if not any(fragments) and not med_prefix:
        if strength_col is not None and size_col is not None:
            s, z = _repair_strength_size_pair(padded[strength_col], padded[size_col])
            if s != padded[strength_col] or z != padded[size_col]:
                padded = list(padded)
                padded[strength_col] = s
                padded[size_col] = z
        return padded

    product_parts, strength, size = _parse_strength_size_from_fragments(
        fragments,
        initial_strength_prefix=med_prefix,
    )
    if not strength and not size and not product_parts:
        return padded

    padded = list(padded)
    padded[med_col] = med_text
    if product_parts:
        suffix = ' '.join(product_parts).strip()
        padded[med_col] = _merge_product_name(padded[med_col], suffix)

    if strength_col is None:
        strength_col = med_col + 1
    if size_col is None:
        size_col = strength_col + 1

    effective_strength = strength or padded[strength_col].strip()
    effective_size = size or padded[size_col].strip()
    if compound_prefix:
        effective_strength = _repair_compound_strength_continuation(
            effective_strength,
            compound_prefix,
        )
    strength, size = _repair_strength_size_pair(effective_strength, effective_size)
    padded[strength_col] = strength
    padded[size_col] = size
    padded[med_col] = _repair_split_medication_words(padded[med_col])

    for idx in range(med_col + 1, fragments_end):
        if idx not in (strength_col, size_col):
            padded[idx] = ''

    if price_values:
        for idx in range(price_start, len(padded)):
            padded[idx] = ''
        for offset, price in enumerate(price_values):
            idx = price_start + offset
            if idx < len(padded):
                padded[idx] = price

    return padded


def _fill_product_name_continuations(data_rows: list[list[str]], headers: list[str]) -> list[list[str]]:
    med_col = _medication_column_index(headers)
    if med_col is None:
        return [_pad_row(row, len(headers)) for row in data_rows]
    last_product = ''
    last_compound_prefix = ''
    strength_col = _strength_column_index(headers)
    filled: list[list[str]] = []
    for row in data_rows:
        padded = _pad_row(row, max(len(headers), len(row)))
        if last_product and not padded[med_col].strip():
            padded[med_col] = last_product
        padded = _repair_pdf_matrix_row(
            padded,
            headers,
            compound_prefix=last_compound_prefix,
        )
        if strength_col is not None:
            strength_val = padded[strength_col].strip()
            prefix = _compound_strength_continuation_prefix(strength_val)
            if prefix:
                last_compound_prefix = prefix
        product = padded[med_col].strip()
        if product:
            last_product = product
        filled.append(padded)
    return filled


def _find_all_matrix_header_rows(table_rows: list[list[str]]) -> list[int]:
    indices: list[int] = []
    for idx, row in enumerate(table_rows):
        normalized = [_normalize_header(cell) for cell in row]
        if _row_has_matrix_header_signals(normalized):
            indices.append(idx)
    return indices


def _parse_pdf_table_segments(rows: list[list[str]]) -> list[dict]:
    """Parse one extracted PDF table, including multi-section catalogs with repeated headers."""
    header_indices = _find_all_matrix_header_rows(rows)
    if not header_indices:
        return []

    parsed: list[dict] = []
    for i, header_idx in enumerate(header_indices):
        end_idx = header_indices[i + 1] if i + 1 < len(header_indices) else len(rows)
        segment = rows[header_idx:end_idx]
        if len(segment) < 2:
            continue
        dataset = _dataset_from_pdf_table(segment, 0)
        if not dataset:
            continue
        segment_rows, _ = _parse_dataset_rows(dataset)
        if segment_rows:
            parsed.extend(segment_rows)
    return parsed


CATALOG_PRICE_LINE_RE = re.compile(
    r'^(?P<body>.+?)\s+Each\s+\$?(?P<price>[\d,]+\.\d{2})\s*$',
    re.IGNORECASE,
)
STRENGTH_ONLY_RE = re.compile(
    r'^[\d./,\s]+(mg|mcg|μg|g|mL|IU)\b',
    re.IGNORECASE,
)


def _split_product_strength(body: str) -> tuple[str, str]:
    match = re.search(
        r'\s+(\d[\d./,\s]*(mg|mcg|μg|g|mL|IU).*)$',
        body,
        re.IGNORECASE,
    )
    if match:
        return body[:match.start()].strip(), match.group(1).strip()
    return body, ''


def _parse_catalog_text_lines(lines: list[str]) -> Dataset | None:
    dataset = Dataset()
    dataset.headers = ['product name', 'strength', 'size', 'price']
    last_product = ''
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.isupper() and len(text) > 12 and not _parse_price(text):
            continue
        match = CATALOG_PRICE_LINE_RE.match(text)
        if not match:
            continue
        body = match.group('body').strip()
        price = match.group('price')
        if STRENGTH_ONLY_RE.match(body) and last_product:
            dataset.append([last_product, body, 'Each', price])
            continue
        product, strength = _split_product_strength(body)
        if not product:
            continue
        last_product = product
        dataset.append([product, strength, 'Each', price])
    return dataset if dataset.height else None


def _pdf_text_to_dataset(content: bytes) -> Dataset | None:
    """Fallback when PDF has no detectable vector tables — parse spaced columns or name+price lines."""
    import pdfplumber
    from io import BytesIO

    lines: list[str] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            lines.extend(line.strip() for line in text.splitlines() if line.strip())

    if not lines:
        return None

    catalog_dataset = _parse_catalog_text_lines(lines)
    if catalog_dataset and catalog_dataset.height:
        return catalog_dataset

    for idx, line in enumerate(lines[:40]):
        parts = re.split(r'\s{2,}|\t', line.strip())
        if len(parts) < 2:
            continue
        headers = _normalize_table_headers(parts)
        if _row_has_matrix_header_signals(headers):
            dataset = Dataset()
            dataset.headers = headers
            for body_line in lines[idx + 1:]:
                body_parts = re.split(r'\s{2,}|\t', body_line.strip())
                if len(body_parts) < 2:
                    continue
                padded = _pad_row(body_parts, len(headers))
                row_map = {headers[i]: padded[i] for i in range(len(headers))}
                if not _get_row_value(row_map, *MEDICATION_KEYS) and not _get_row_value(row_map, *SKU_KEYS):
                    continue
                if not any(_parse_price(padded[i]) is not None for i in range(1, len(padded))):
                    continue
                dataset.append(padded)
            if dataset.height:
                return dataset

    dataset = Dataset()
    dataset.headers = ['medication', 'quoted price (unit)']
    for line in lines:
        match = re.match(r'^(.+?)\s+(?:RM|USD|EUR|\$)?\s*([\d,]+\.\d{2})\s*$', line.strip(), re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).strip(' .-')
        if len(name) < 2:
            continue
        dataset.append([name, match.group(2)])
    return dataset if dataset.height else None


def _should_skip_pdf_data_row(row: list[str], headers: list[str]) -> bool:
    padded = _pad_row(row, len(headers))
    row_map = {headers[i]: padded[i] for i in range(len(headers))}
    medication = _get_row_value(row_map, *MEDICATION_KEYS)
    sku = _get_row_value(row_map, *SKU_KEYS)
    if not medication and not sku:
        return True
    non_empty = [cell.strip() for cell in padded if cell.strip()]
    if len(non_empty) == 1 and non_empty[0].isupper() and len(non_empty[0]) > 12:
        return True
    has_price = any(_parse_price(cell) is not None for cell in padded)
    if medication and medication.isupper() and not has_price:
        strength = _get_row_value(row_map, *STRENGTH_KEYS)
        if not strength or not re.search(r'\d', strength):
            return True
    if not has_price:
        return True
    return False


def _dataset_from_pdf_table(rows: list[list[str]], header_idx: int) -> Dataset | None:
    if header_idx >= len(rows):
        return None
    header_row = rows[header_idx]
    data_rows = rows[header_idx + 1:]
    groups = _detect_column_groups(header_row)

    dataset = Dataset()
    for start, end in groups:
        group_header = [header_row[i] if i < len(header_row) else '' for i in range(start, end)]
        headers = _normalize_table_headers(group_header)
        if not _row_has_matrix_header_signals(headers):
            continue
        group_data = _fill_product_name_continuations(
            _slice_table_columns(data_rows, start, end),
            headers,
        )
        if not dataset.headers:
            dataset.headers = headers
        for row in group_data:
            if _should_skip_pdf_data_row(row, headers):
                continue
            dataset.append(_pad_row(row, len(headers)))
    return dataset if dataset.height else None


_PDF_TABLE_SETTINGS: tuple[dict | None, ...] = (
    None,
    {
        'vertical_strategy': 'lines',
        'horizontal_strategy': 'lines',
        'snap_tolerance': 3,
        'join_tolerance': 3,
    },
    {
        'vertical_strategy': 'text',
        'horizontal_strategy': 'text',
        'snap_tolerance': 5,
        'join_tolerance': 5,
    },
)


def _extract_tables_for_page(page, settings: dict | None):
    if settings is None:
        return page.extract_tables() or []
    return page.extract_tables(settings) or []


def _parse_tables_from_page(page) -> list[dict]:
    """Try multiple pdfplumber strategies; split two-column pages when needed."""
    parsed: list[dict] = []

    def try_page(scan_page) -> bool:
        before = len(parsed)
        for settings in _PDF_TABLE_SETTINGS:
            for table in _extract_tables_for_page(scan_page, settings):
                rows = _clean_pdf_table(table)
                segment_rows = _parse_pdf_table_segments(rows)
                if segment_rows:
                    parsed.extend(segment_rows)
        return len(parsed) > before

    if try_page(page):
        return parsed

    mid = page.width / 2
    if mid > 0:
        try_page(page.crop((0, 0, mid, page.height)))
        try_page(page.crop((mid, 0, page.width, page.height)))
    return parsed


def _extract_rows_from_pdf_tables(content: bytes) -> list[dict]:
    import pdfplumber
    from io import BytesIO

    all_rows: list[dict] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_rows = _parse_tables_from_page(page)
            if page_rows:
                all_rows.extend(page_rows)
    return all_rows


def _parse_pdf_price_matrix_file(content: bytes) -> tuple[list[dict] | None, str | None]:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return None, 'PDF support is not installed on the server (pdfplumber).'

    try:
        all_rows = _extract_rows_from_pdf_tables(content)
    except Exception as exc:
        return None, f'Could not read PDF: {exc}'

    if not all_rows:
        text_dataset = _pdf_text_to_dataset(content)
        if text_dataset and text_dataset.height:
            return _parse_dataset_rows(text_dataset)
        return None, (
            'Could not find a price table in the PDF. '
            'Use a table-based price list with Medication/Product and price columns, or upload Excel/CSV.'
        )

    for idx, row in enumerate(all_rows, start=1):
        row['row_index'] = idx
    return all_rows, None


def _load_pdf_as_dataset(content: bytes) -> tuple[Dataset | None, str | None]:
    """Legacy helper — prefer _parse_pdf_price_matrix_file for direct row parsing."""
    rows, error = _parse_pdf_price_matrix_file(content)
    if error:
        return None, error
    if not rows:
        return None, 'No price rows found in PDF.'
    dataset = Dataset()
    dataset.headers = ['medication', 'strength', 'form', 'size', 'notes', 'sku', 'unit_price']
    for row in rows:
        tier = row['tiers'][0] if row.get('tiers') else {}
        dataset.append([
            row.get('medication', ''),
            row.get('strength', ''),
            row.get('form', ''),
            row.get('size', ''),
            row.get('notes', ''),
            row.get('sku', ''),
            str(tier.get('unit_price', '')),
        ])
    return dataset, None


def _load_matrix_dataset(file, lower_name: str) -> tuple[Dataset | None, str | None]:
    if lower_name.endswith('.csv'):
        content = file.read()
        try:
            decoded = content.decode('utf-8')
        except UnicodeDecodeError:
            decoded = content.decode('latin-1')
        dataset = Dataset()
        dataset.load(decoded, format='csv')
        return dataset, None
    if lower_name.endswith(('.xls', '.xlsx')):
        dataset = Dataset()
        dataset.load(file.read(), format='xlsx')
        return dataset, None
    return None, 'Invalid file format. Use .csv, .xls, .xlsx, or .pdf.'


def _parse_dataset_rows(dataset: Dataset) -> tuple[list[dict] | None, str | None]:
    if not dataset.height:
        return [], None

    headers = [_normalize_header(h) for h in dataset.headers]
    tier_columns: list[tuple[int, int | None, int]] = []
    single_price_col: int | None = None

    for idx, header in enumerate(headers):
        if not header:
            continue
        tier = _parse_tier_from_header(header)
        if tier:
            tier_columns.append((tier[0], tier[1], idx))
            continue
        if header in SINGLE_PRICE_KEYS and single_price_col is None:
            single_price_col = idx

    rows: list[dict] = []
    last_medication = ''
    for row_index, raw in enumerate(dataset.dict, start=1):
        nr = _normalize_import_row(raw)
        medication = _get_row_value(nr, *MEDICATION_KEYS)
        if medication:
            last_medication = medication
        elif last_medication:
            medication = last_medication
        strength = _get_row_value(nr, *STRENGTH_KEYS)
        form = _get_row_value(nr, *FORM_KEYS)
        size = _get_row_value(nr, *SIZE_KEYS)
        medication, med_prefix = _peel_trailing_strength_from_name(medication)
        if med_prefix and strength:
            strength = _join_strength_prefix(med_prefix, strength)
        elif med_prefix and not strength:
            strength = med_prefix
        strength, size = _repair_strength_size_pair(strength, size)
        medication = _repair_split_medication_words(medication)
        notes = _get_row_value(nr, *NOTES_KEYS)
        sku = _get_row_value(nr, *SKU_KEYS)

        if not medication and not sku:
            continue

        tiers: list[dict[str, Any]] = []
        if tier_columns:
            for min_qty, max_qty, col_idx in tier_columns:
                header_key = headers[col_idx]
                price = _parse_price(nr.get(header_key))
                if price is not None:
                    tiers.append({
                        'min_quantity': min_qty,
                        'max_quantity': max_qty,
                        'unit_price': price,
                    })
        elif single_price_col is not None:
            header_key = headers[single_price_col]
            price = _parse_price(nr.get(header_key))
            if price is not None:
                tiers.append({
                    'min_quantity': 1,
                    'max_quantity': None,
                    'unit_price': price,
                })
        else:
            for header, value in nr.items():
                tier = _parse_tier_from_header(header)
                if not tier:
                    continue
                price = _parse_price(value)
                if price is not None:
                    tiers.append({
                        'min_quantity': tier[0],
                        'max_quantity': tier[1],
                        'unit_price': price,
                    })

        if not tiers:
            continue

        tiers.sort(key=lambda t: t['min_quantity'])
        rows.append({
            'row_index': row_index,
            'medication': medication,
            'strength': strength,
            'form': form,
            'size': size,
            'notes': notes,
            'sku': sku,
            'match_name': _composite_line_name(medication, strength, size) if medication else '',
            'tiers': tiers,
        })

    if not rows:
        return None, 'No price rows found. Check column headers (Medication, Strength, Size, and tier price columns).'

    return rows, None


def parse_supplier_price_matrix_file(file) -> tuple[list[dict] | None, str | None]:
    """
    Parse CSV/XLSX/PDF supplier price list. Returns rows:
    medication, strength, form, size, notes, sku, tiers[{min_quantity,max_quantity,unit_price}]
    """
    name = getattr(file, 'name', '') or ''
    lower_name = name.lower()
    if not lower_name.endswith(('.csv', '.xls', '.xlsx', '.pdf')):
        return None, 'Invalid file format. Use .csv, .xls, .xlsx, or .pdf.'

    try:
        if lower_name.endswith('.pdf'):
            return _parse_pdf_price_matrix_file(file.read())
        dataset, load_error = _load_matrix_dataset(file, lower_name)
        if load_error:
            return None, load_error
        if dataset is None:
            return None, 'Could not read the uploaded file.'
    except Exception as exc:
        return None, str(exc)

    return _parse_dataset_rows(dataset)


def default_matrix_unit_price(entry) -> Decimal | None:
    tier = entry.tiers.order_by('min_quantity').first()
    return tier.unit_price if tier else None


def build_supplier_costs_from_matrix(product) -> list[dict]:
    from inventory.models import SupplierPriceMatrixEntry

    costs: dict[int, dict] = {}
    entries = (
        SupplierPriceMatrixEntry.objects.filter(product=product)
        .select_related('supplier')
        .prefetch_related('tiers')
    )
    for entry in entries:
        unit = default_matrix_unit_price(entry)
        if unit is None:
            continue
        sid = entry.supplier_id
        existing = costs.get(sid)
        if existing and existing['updated_at'] >= entry.updated_at:
            continue
        costs[sid] = {
            'supplier_id': sid,
            'supplier_name': entry.supplier.name or 'Unknown',
            'cost': unit,
            'date': entry.effective_date or entry.updated_at.date(),
            'updated_at': entry.updated_at,
            'source': 'matrix',
        }
    return sorted(costs.values(), key=lambda x: x['supplier_name'])


def build_supplier_costs_from_quotations(product) -> list[dict]:
    from inventory.models import QuotationItem

    supplier_costs: list[dict] = []
    seen_suppliers: set[int] = set()

    if hasattr(product, 'latest_quotation_items') and product.latest_quotation_items:
        quotation_items = product.latest_quotation_items
    else:
        quotation_items = (
            QuotationItem.objects.filter(product=product)
            .select_related('quotation', 'quotation__supplier')
            .prefetch_related('quotation__items')
            .order_by('-quotation__date_quoted')
        )

    for item in quotation_items:
        sup_id = item.quotation.supplier_id
        if sup_id in seen_suppliers:
            continue
        seen_suppliers.add(sup_id)
        cost = item.landed_cost_per_unit
        if cost is not None:
            supplier_costs.append({
                'supplier_id': sup_id,
                'supplier_name': item.quotation.supplier.name or 'Unknown',
                'cost': cost,
                'date': item.quotation.date_quoted,
                'source': 'quotation',
            })
    return supplier_costs


def invoice_item_landed_cost_per_unit(invoice_item, invoice_subtotal: Decimal | None = None) -> Decimal | None:
    """Unit price in MYR plus pro-rata share of invoice transportation cost."""
    if invoice_item is None or not invoice_item.quantity or invoice_item.unit_price is None:
        return None
    inv = invoice_item.invoice
    subtotal = invoice_subtotal if invoice_subtotal is not None else (inv.subtotal or Decimal('0'))
    transport = inv.transportation_cost or Decimal('0')
    unit_myr = invoice_item.unit_price
    qty = Decimal(str(invoice_item.quantity))
    if subtotal > 0 and transport > 0:
        item_total = qty * unit_myr
        return unit_myr + (transport * (item_total / subtotal)) / qty
    return unit_myr


def latest_invoice_cost_detail_for_product(product) -> dict | None:
    """Latest invoice line landed cost breakdown for pricing UI."""
    from sales.models import InvoiceItem

    latest_inv_item = (
        InvoiceItem.objects.filter(product=product, quantity__gt=0)
        .select_related('invoice', 'invoice__supplier')
        .order_by('-invoice__date_issued', '-invoice__created_at', '-pk')
        .first()
    )
    if latest_inv_item is None:
        return None

    inv = latest_inv_item.invoice
    unit_myr = latest_inv_item.unit_price
    landed_per_unit = invoice_item_landed_cost_per_unit(latest_inv_item)
    if landed_per_unit is None:
        return None

    src_currency = (getattr(latest_inv_item, 'original_currency', '') or '').upper()
    src_price = getattr(latest_inv_item, 'unit_price_source', None)
    return {
        'invoice_id': inv.invoice_id,
        'invoice_date': inv.date_issued.isoformat() if inv.date_issued else None,
        'supplier_name': inv.supplier.name if inv.supplier else '',
        'unit_price_myr': str(unit_myr.quantize(Decimal('0.01'))),
        'transport_per_unit': str((landed_per_unit - unit_myr).quantize(Decimal('0.01'))),
        'landed_cost': str(landed_per_unit.quantize(Decimal('0.01'))),
        'original_currency': src_currency if src_currency and src_currency != 'MYR' else '',
        'unit_price_source': str(src_price.quantize(Decimal('0.0001'))) if src_price is not None else None,
    }


def latest_invoice_landed_cost_for_product(product) -> Decimal | None:
    detail = latest_invoice_cost_detail_for_product(product)
    if not detail:
        return None
    return Decimal(detail['landed_cost'])


def build_supplier_costs_from_invoices(product) -> list[dict]:
    """Latest invoice landed cost per supplier for this product."""
    from sales.models import InvoiceItem

    items = (
        InvoiceItem.objects.filter(product=product, quantity__gt=0)
        .select_related('invoice', 'invoice__supplier')
        .order_by('-invoice__date_issued', '-invoice__created_at', '-pk')
    )
    seen_suppliers: set[int] = set()
    supplier_costs: list[dict] = []
    for item in items:
        sup_id = item.invoice.supplier_id
        if not sup_id or sup_id in seen_suppliers:
            continue
        landed = invoice_item_landed_cost_per_unit(item)
        if landed is None:
            continue
        seen_suppliers.add(sup_id)
        supplier_costs.append({
            'supplier_id': sup_id,
            'supplier_name': item.invoice.supplier.name or 'Unknown',
            'cost': landed,
            'date': item.invoice.date_issued,
            'source': 'invoice',
        })
    return supplier_costs


def get_product_supplier_costs(product) -> list[dict]:
    """Matrix prices take precedence, then invoice landed cost, then legacy quotations."""
    matrix_costs = build_supplier_costs_from_matrix(product)
    matrix_by_supplier = {c['supplier_id']: c for c in matrix_costs}
    invoice_costs = build_supplier_costs_from_invoices(product)
    invoice_by_supplier = {c['supplier_id']: c for c in invoice_costs}
    merged = list(matrix_costs)

    for row in invoice_costs:
        if row['supplier_id'] not in matrix_by_supplier:
            merged.append(row)

    for row in build_supplier_costs_from_quotations(product):
        sid = row['supplier_id']
        if sid not in matrix_by_supplier and sid not in invoice_by_supplier:
            merged.append(row)

    return sorted(merged, key=lambda x: x['supplier_name'])


def _matrix_search_tokens(search_query: str) -> list[str]:
    tokens = [part for part in search_query.split() if len(part) >= 2]
    if not tokens and search_query:
        return [search_query]
    return tokens


def serialize_quotation_matrix_item(item, precomputed_cost=None) -> dict:
    """Serialize one quotation line as a matrix-style row."""
    cost = precomputed_cost if precomputed_cost is not None else item.landed_cost_per_unit
    q = item.quotation
    return {
        'id': item.pk,
        'source': 'quotation',
        'quotation_id': q.quotation_id,
        'supplier_id': q.supplier_id,
        'supplier_name': q.supplier.name if q.supplier else 'Unknown',
        'product_id': item.product_id,
        'product_name': item.product.name,
        'product_sku': item.product.sku or None,
        'line_medication': (item.line_product_label or item.product.name or '').strip(),
        'strength': '',
        'form': '',
        'size': '',
        'notes': '',
        'price_currency': item.input_currency or 'MYR',
        'conversion_rate': None,
        'source_filename': f'Quotation {q.quotation_id}',
        'effective_date': q.date_quoted,
        'updated_at': q.date_quoted.isoformat() if q.date_quoted else None,
        'tiers': [{
            'min_quantity': 1,
            'max_quantity': None,
            'unit_price': cost,
        }] if cost is not None else [],
    }


def list_quotation_matrix_rows(supplier_ids=None, search_query: str = '') -> list[dict]:
    """
    Matrix-style rows from latest legacy quotation line per (supplier, product)
    when no SupplierPriceMatrixEntry exists for that pair.

    Performance: avoids prefetch_related('quotation__items') by batch-computing
    quotation total values in a single aggregation query.
    """
    from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum

    from inventory.models import QuotationItem, SupplierPriceMatrixEntry

    matrix_pairs = set(
        SupplierPriceMatrixEntry.objects.filter(product_id__isnull=False)
        .values_list('supplier_id', 'product_id')
    )

    items_qs = (
        QuotationItem.objects.filter(product_id__isnull=False)
        .select_related('product', 'quotation', 'quotation__supplier')
        # No prefetch_related('quotation__items') — totals are batched below
        .order_by('-quotation__date_quoted', '-pk')
    )
    if supplier_ids:
        items_qs = items_qs.filter(quotation__supplier_id__in=supplier_ids)
    for token in _matrix_search_tokens(search_query):
        items_qs = items_qs.filter(
            Q(product__name__icontains=token)
            | Q(product__sku__icontains=token)
            | Q(line_product_label__icontains=token)
            | Q(quotation__supplier__name__icontains=token)
        )

    items = list(items_qs)

    # Batch-fetch quotation totals (one aggregation query instead of N queries)
    quotation_ids = list({item.quotation_id for item in items})
    quotation_totals: dict[int, Decimal] = {}
    if quotation_ids:
        for row in (
            QuotationItem.objects.filter(quotation_id__in=quotation_ids)
            .values('quotation_id')
            .annotate(
                total=Sum(
                    ExpressionWrapper(
                        F('quantity') * F('quoted_price'),
                        output_field=DecimalField(max_digits=20, decimal_places=4),
                    )
                )
            )
        ):
            if row['total'] is not None:
                quotation_totals[row['quotation_id']] = Decimal(str(row['total']))

    seen: set[tuple[int, int]] = set()
    rows: list[dict] = []
    for item in items:
        key = (item.quotation.supplier_id, item.product_id)
        if key in seen or key in matrix_pairs:
            continue
        qty = item.quantity
        quoted_price = item.quoted_price
        if not qty or not quoted_price:
            continue
        quotation_total = quotation_totals.get(item.quotation_id, Decimal('0'))
        transport = item.quotation.transportation_cost or Decimal('0')
        if quotation_total > 0 and transport > 0:
            item_total = Decimal(qty) * quoted_price
            item_share = transport * (item_total / quotation_total)
            landed_cost = (item_total + item_share) / Decimal(qty)
        else:
            landed_cost = quoted_price
        seen.add(key)
        rows.append(serialize_quotation_matrix_item(item, precomputed_cost=landed_cost))
    return rows


def latest_matrix_unit_price_for_product(product) -> Decimal | None:
    from inventory.models import SupplierPriceMatrixEntry

    entry = (
        SupplierPriceMatrixEntry.objects.filter(product=product)
        .prefetch_related('tiers')
        .order_by('-updated_at')
        .first()
    )
    if not entry:
        return None
    return default_matrix_unit_price(entry)


def sync_saved_base_costs_for_products(product_ids: list[int]) -> None:
    from product.models import Product
    from product.pricing_sync import reconcile_saved_base_cost_with_quotations

    for pid in product_ids:
        product = Product.objects.filter(pk=pid).first()
        if not product:
            continue
        supplier_costs = get_product_supplier_costs(product)
        reconcile_saved_base_cost_with_quotations(product, supplier_costs)
