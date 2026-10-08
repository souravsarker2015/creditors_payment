from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def group_bd(digits):
    """'12500000' → '1,25,00,000': the last three digits, then pairs (lakh, crore)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + pairs + [tail])


def bd_number(value, places=2):
    """Plain figure with Bangladeshi grouping, for statements and exports:
    12345678.5 → '1,23,45,678.50'."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(amount):.{places}f}".partition(".")
    return sign + group_bd(whole) + (f".{frac}" if frac else "")


def _format(value, force_sign=False):
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    amount = amount.quantize(Decimal("0.01"))
    if amount < 0:
        sign = "−"
    elif force_sign and amount > 0:
        sign = "+"
    else:
        sign = ""
    amount = abs(amount)
    # Lakh and crore grouping (৳1,25,000), the way amounts are read in Bangladesh.
    # Whole amounts drop the ".00" to keep figures short on small screens.
    body = bd_number(amount, 0 if amount == amount.to_integral_value() else 2)
    return f"{sign}৳{body}"


@register.filter
def money(value):
    """৳ amount with Bangladeshi grouping, e.g. 1234567.5 -> ৳12,34,567.50."""
    return _format(value)


@register.filter
def signed_money(value):
    """Like `money`, but positive amounts get an explicit "+"."""
    return _format(value, force_sign=True)


@register.simple_tag(takes_context=True)
def query_with(context, **kwargs):
    """The current query string with the given params replaced (and `page`
    dropped), e.g. {% query_with status="inactive" %} -> "?q=x&status=inactive"."""
    params = context["request"].GET.copy()
    params.pop("page", None)
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag
def quick_add_popup(kind):
    """Context for the quick-add popup of one kind (form, url, title)."""
    from apps.core.quick_create import popup_context

    return popup_context(kind)



@register.simple_tag
def asset(path):
    """{% static %} plus ?v=<last modified> so browsers (phones especially)
    fetch a changed CSS/JS file instead of reusing a stale cached copy.
    With a hashed storage (ManifestStaticFilesStorage) the URL already
    changes, and the extra query string is harmless."""
    import os

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    return f"{url}?v={int(os.path.getmtime(found))}"


def whatsapp_number(phone):
    """Local Bangladeshi numbers (01XXXXXXXXX) → 8801XXXXXXXXX, the
    international form wa.me needs. Other numbers keep their digits."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("01"):
        return "88" + digits
    if digits.startswith("00"):
        return digits[2:]
    return digits


@register.simple_tag
def reminder(name, amount, due_date=None, phone=""):
    """A polite payment reminder plus ready-made WhatsApp / SMS links."""
    from urllib.parse import quote

    from django.utils.formats import date_format
    from django.utils.translation import gettext as _

    values = {"name": name, "amount": _format(amount)}
    if due_date:
        values["date"] = date_format(due_date, "j F Y")
        text = _("Hello %(name)s, a friendly reminder that %(amount)s is still due (due date: %(date)s). "
                 "Please pay when convenient. Thank you!") % values
    else:
        text = _("Hello %(name)s, a friendly reminder that %(amount)s is still due. "
                 "Please pay when convenient. Thank you!") % values
    number = whatsapp_number(phone)
    return {
        "text": text,
        "whatsapp": f"https://wa.me/{number}?text={quote(text)}",
        # "?&body=" works on both Android and iOS.
        "sms": f"sms:{phone}?&body={quote(text)}",
        "has_phone": bool(number),
    }


@register.filter
def undo_id(message):
    """The Recently deleted id carried by a "deleted" message (extra_tags "undo:12"), or ""."""
    for tag in (getattr(message, "extra_tags", "") or "").split():
        if tag.startswith("undo:") and tag[5:].isdigit():
            return tag[5:]
    return ""


@register.filter
def by_month(items, attr="date"):
    """Rows (newest first) in month groups: [{"month": date, "items": [...]}].
    `attr` is the date's attribute name, or its index for tuples."""
    groups = []
    for item in items:
        day = item[int(attr)] if isinstance(item, (tuple, list)) else getattr(item, attr)
        if not groups or (groups[-1]["month"].year, groups[-1]["month"].month) != (day.year, day.month):
            groups.append({"month": day.replace(day=1), "items": []})
        groups[-1]["items"].append(item)
    return groups


@register.filter
def sum_attr(items, attr):
    """Adds up one attribute over rows (skips empty ones)."""
    total = Decimal(0)
    for item in items:
        value = getattr(item, attr, None)
        if value is not None:
            total += Decimal(value)
    return total
