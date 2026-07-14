"""Convert Ringgit Malaysia amounts to invoice words (e.g. RINGGIT MALAYSIA : … ONLY)."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


_ONES = (
    '', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
    'TEN', 'ELEVEN', 'TWELVE', 'THIRTEEN', 'FOURTEEN', 'FIFTEEN', 'SIXTEEN',
    'SEVENTEEN', 'EIGHTEEN', 'NINETEEN',
)
_TENS = (
    '', '', 'TWENTY', 'THIRTY', 'FORTY', 'FIFTY', 'SIXTY', 'SEVENTY', 'EIGHTY', 'NINETY',
)


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones:
        return f'{_TENS[tens]} {_ONES[ones]}'
    return _TENS[tens]


def _three_digits(n: int, *, use_and: bool = False) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f'{_ONES[hundreds]} HUNDRED')
    if rest:
        if use_and and hundreds:
            parts.append(f'AND {_two_digits(rest)}')
        else:
            parts.append(_two_digits(rest))
    return ' '.join(parts)


def _integer_to_words(n: int) -> str:
    if n == 0:
        return 'ZERO'
    if n < 0:
        return f'NEGATIVE {_integer_to_words(-n)}'

    scales = ('', 'THOUSAND', 'MILLION', 'BILLION', 'TRILLION')
    chunks = []
    scale_idx = 0
    while n > 0:
        n, rem = divmod(n, 1000)
        if rem:
            # Insert AND only in the least-significant hundred group (matches invoice sample)
            chunk = _three_digits(rem, use_and=(scale_idx == 0))
            scale = scales[scale_idx] if scale_idx < len(scales) else f'10^{scale_idx * 3}'
            chunks.append(f'{chunk} {scale}'.strip() if scale else chunk)
        scale_idx += 1

    return ' '.join(reversed(chunks))


def ringgit_amount_in_words(amount) -> str:
    """
    Return invoice-style amount in words.

    Whole ringgit: RINGGIT MALAYSIA : SIX THOUSAND SEVEN HUNDRED AND NINE ONLY
    With sen:     RINGGIT MALAYSIA : ONE HUNDRED AND TWENTY AND 50 SEN ONLY
    """
    try:
        value = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        value = Decimal('0.00')

    negative = value < 0
    value = abs(value)
    ringgit = int(value)
    sen = int((value - Decimal(ringgit)) * 100)

    words = _integer_to_words(ringgit)
    if negative:
        words = f'NEGATIVE {words}'

    if sen:
        return f'RINGGIT MALAYSIA : {words} AND {sen:02d} SEN ONLY'
    return f'RINGGIT MALAYSIA : {words} ONLY'
