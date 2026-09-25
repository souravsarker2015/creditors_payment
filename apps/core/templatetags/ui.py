from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


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
    # Whole amounts drop the ".00" to keep figures short on small screens.
    body = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
    return f"{sign}৳{body}"


@register.filter
def money(value):
    """৳ amount with thousands separators, e.g. 1234567.5 -> ৳1,234,567.50."""
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
