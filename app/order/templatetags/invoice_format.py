from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter(name='rm_amount')
def rm_amount(value):
    """Format a money value as 1,234.56 (comma thousands, 2 decimals)."""
    if value is None or value == '':
        return '0.00'
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return '0.00'
    # Use Python formatting for reliable comma separators regardless of locale.
    return f'{amount:,.2f}'
