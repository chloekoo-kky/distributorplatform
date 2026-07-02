from django import template

from core.dates import format_display_date, format_display_datetime

register = template.Library()


@register.filter
def display_date(value):
    return format_display_date(value)


@register.filter
def display_datetime(value):
    return format_display_datetime(value)
