from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()


def group_bd(digits):
    """'12500000' → '1,25,00,000' (last three, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + pairs + [tail])


def _dec(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter
def bdt(value, places=None):
    """৳ with Bangladeshi grouping: 125000 → ৳1,25,000; 1234.5 → ৳1,234.50."""
    amount = _dec(value)
    if amount is None:
        return value
    amount = amount.quantize(Decimal("0.01"))
    sign = "−" if amount < 0 else ""
    amount = abs(amount)
    whole, frac = f"{amount:.2f}".split(".")
    body = group_bd(whole) + ("" if frac == "00" and places is None else "." + frac)
    return f"{sign}৳{body}"


@register.filter
def num(value):
    """Plain number, Bangladeshi grouping, no trailing zeros: 1250.500 → 1,250.5."""
    amount = _dec(value)
    if amount is None:
        return value
    sign = "−" if amount < 0 else ""
    text = f"{abs(amount):f}"
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    return sign + group_bd(whole) + (f".{frac}" if frac else "")


@register.simple_tag
def qty(quantity, unit, base=None):
    """'5 mon' plus, when it isn't already the base unit, '= 200 kg'."""
    if unit is None:
        return num(quantity)
    main = format_html("{} {}", num(quantity), unit.symbol)
    if unit.is_base or unit.factor == 1:
        return main
    base_unit = base or unit.base_unit()
    if base_unit is None:
        return main
    return format_html('{} <span class="qty-base">= {} {}</span>', main, num(Decimal(quantity) * unit.factor), base_unit.symbol)


@register.filter
def days_until(value):
    """Whole days from today to a date (negative when it's past)."""
    from datetime import date

    return (value - date.today()).days if value else 0


@register.filter
def absolute(value):
    try:
        return abs(value)
    except TypeError:
        return value


@register.simple_tag(takes_context=True)
def biz_quick_add(context, kind):
    """Context for a business "+ Add new" popup (see core/crud.py)."""
    from apps.business.core.crud import quick_add_context

    request = context.get("request")
    business = getattr(request, "business", None) or context.get("business")
    return quick_add_context(kind, business)
