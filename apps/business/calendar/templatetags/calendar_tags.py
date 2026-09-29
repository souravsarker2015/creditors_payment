from django import template
from django.utils.translation import get_language

from ..bangla import bn_digits, to_bangla

register = template.Library()


@register.filter
def loc_num(value):
    """Digits in Bangla when the app is in Bangla."""
    return bn_digits(value) if (get_language() or "").startswith("bn") else value


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key.isoformat() if hasattr(key, "isoformat") else key)
    except AttributeError:
        return None


@register.filter
def split(value):
    return value.split()


@register.filter
def bangla_date(value):
    """'১৪ আশ্বিন ১৪৩৩' in Bangla, '14 Ashwin 1433' in English."""
    if not value:
        return ""
    return to_bangla(value).format(bangla=(get_language() or "").startswith("bn"))
