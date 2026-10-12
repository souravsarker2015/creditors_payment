from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.productivity import services

register = template.Library()


@register.filter
def hm(seconds):
    """3725 → 1h 02m."""
    return services.hm(seconds)


@register.filter
def minutes_hm(minutes):
    return services.hm((minutes or 0) * 60)


@register.filter
def hours(seconds):
    """3725 → 1.03 (for a spreadsheet-like table)."""
    return f"{(seconds or 0) / 3600:.2f}"


@register.filter
def due_label(day):
    if not day:
        return ""
    today = timezone.localdate()
    if day == today:
        return _("Today")
    if day == today + timedelta(days=1):
        return _("Tomorrow")
    if day == today - timedelta(days=1):
        return _("Yesterday")
    if today < day <= today + timedelta(days=6):
        return date_format(day, "l")
    return date_format(day, "j M" if day.year == today.year else "j M Y")


@register.filter
def due_tone(task):
    if not task.due_date or task.is_done:
        return ""
    today = timezone.localdate()
    return "late" if task.due_date < today else ("today" if task.due_date == today else "")


@register.filter
def checklist_counts(task):
    items = list(task.checklist.all())
    return f"{sum(1 for i in items if i.done)}/{len(items)}" if items else ""


@register.filter
def local_time(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else ""


@register.filter
def plain(text):
    """Markdown without its marks, for a one-line preview."""
    import re

    text = re.sub(r"```.*?(```|$)", " ", text or "", flags=re.S)
    text = re.sub(r"^\s{0,3}(#{1,6}\s+|[-*+]\s+(\[[ xX]\]\s+)?|\d+\.\s+|>\s?)", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)            # [link](url) → link
    text = re.sub(r"`+|~~|\*+|(?<!\w)_+|_+(?!\w)", "", text)        # marks, but not the _ in work_mem
    return " ".join(text.split())


_ICONS = None


def _icon_table():
    """name → <svg>, read once from templates/partials/icon.html (the app's
    icon set). A dictionary lookup instead of the template's long if/elif
    chain keeps long task lists quick to draw."""
    global _ICONS
    if _ICONS is None:
        import re

        from django.template.loader import get_template

        source = open(get_template("partials/icon.html").origin.name, encoding="utf-8").read()
        _ICONS = {m.group(1): m.group(2).strip() for m in re.finditer(r'name == "([\w-]+)" %\}(.*?)(?=\{% (?:elif|endif))', source, re.S)}
    return _ICONS


@register.simple_tag
def icon(name):
    from django.utils.safestring import mark_safe

    return mark_safe(_icon_table().get(name, ""))


@register.filter
def split_words(text):
    return (text or "").split()


@register.filter
def goal_days_left(goal):
    return goal.days_left()


@register.filter
def abs_int(value):
    try:
        return abs(int(value))
    except (TypeError, ValueError):
        return 0


@register.filter
def get_item(mapping, key):
    return (mapping or {}).get(key, "")


@register.filter
def first_open(steps):
    return next((st for st in steps if not st.done), None)


@register.filter
def escapejs_json(value):
    """A string as a JavaScript literal, safe inside an HTML attribute."""
    import json

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    return mark_safe(escape(json.dumps(str(value or ""))))
