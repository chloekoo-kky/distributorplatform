from datetime import date, datetime

from django.utils import timezone

DISPLAY_DATE_FORMAT = '%d/%m/%Y'
DISPLAY_DATETIME_FORMAT = '%d/%m/%Y %H:%M'


def _coerce_datetime(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def format_display_date(value):
    """Format a date/datetime/ISO string for user-visible display."""
    if value is None:
        return ''
    if isinstance(value, str):
        s = value.strip()
        if not s or s == '-':
            return ''
        if len(s) >= 10 and s[2:3] == '/' and s[5:6] == '/':
            return s[:10]
        if len(s) >= 10 and s[4:5] == '-':
            try:
                parsed = datetime.strptime(s[:10], '%Y-%m-%d').date()
                return parsed.strftime(DISPLAY_DATE_FORMAT)
            except ValueError:
                pass
        dt = _coerce_datetime(datetime.fromisoformat(s.replace('Z', '+00:00'))) if 'T' in s else None
        if dt:
            return dt.strftime(DISPLAY_DATE_FORMAT)
        return s

    dt = _coerce_datetime(value)
    if dt:
        return dt.strftime(DISPLAY_DATE_FORMAT)
    return str(value)


def format_display_datetime(value):
    """Format a datetime/ISO string for user-visible display."""
    if value is None:
        return ''
    if isinstance(value, str):
        s = value.strip()
        if not s or s == '-':
            return ''
        if len(s) >= 16 and s[2:3] == '/' and s[5:6] == '/' and s[10:11] == ' ':
            return s[:16]
        try:
            normalized = s.replace('Z', '+00:00')
            if 'T' in normalized or '+' in normalized[10:] or normalized.count('-') >= 2:
                dt = datetime.fromisoformat(normalized)
                if timezone.is_aware(dt):
                    dt = timezone.localtime(dt)
                return dt.strftime(DISPLAY_DATETIME_FORMAT)
        except ValueError:
            pass
        if len(s) >= 10 and s[4:5] == '-':
            try:
                parsed = datetime.strptime(s[:16], '%Y-%m-%d %H:%M')
                return parsed.strftime(DISPLAY_DATETIME_FORMAT)
            except ValueError:
                try:
                    parsed = datetime.strptime(s[:10], '%Y-%m-%d')
                    return parsed.strftime(DISPLAY_DATE_FORMAT)
                except ValueError:
                    pass
        return format_display_date(s)

    dt = _coerce_datetime(value)
    if dt:
        return dt.strftime(DISPLAY_DATETIME_FORMAT)
    return str(value)
