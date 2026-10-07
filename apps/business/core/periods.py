"""Bangladesh's financial (tax) year runs from 1 July to 30 June."""
from datetime import date, timedelta

from django.utils.translation import gettext as _


def fy_start(day):
    """1 July of the financial year `day` falls in."""
    return date(day.year if day.month >= 7 else day.year - 1, 7, 1)


def fy_end(day):
    return date(fy_start(day).year + 1, 6, 30)


def last_fy(day):
    """(start, end) of the financial year before the one `day` is in."""
    end = fy_start(day) - timedelta(days=1)
    return fy_start(end), end


def fy_label(day):
    """“FY 2026–27”."""
    start = fy_start(day).year
    return _("FY %(from)s–%(to)s") % {"from": start, "to": str(start + 1)[-2:]}
