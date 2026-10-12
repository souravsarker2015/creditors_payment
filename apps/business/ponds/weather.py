"""Tonight's weather and the risk of oxygen running low in the ponds.

Ponds lose oxygen at night, when algae stop making it. It runs lowest before
dawn after a day with little sun (cloud), on hot nights (warm water holds
less oxygen) and when there's no wind to stir the surface. Heavy rain can
also turn a pond over. The forecast comes from Open-Meteo (free, no key) for
the farm's location, kept for a couple of hours, and anything that goes wrong
just means no warning — never a broken page.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen

from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext as _

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 4                # seconds; a slow answer is no answer
KEEP = 2 * 60 * 60         # a forecast is kept this long
HOT_C = 28                 # night air this warm keeps the water warm
CLOUDY_PCT = 70
STILL_KMH = 8
HEAVY_RAIN_MM = 20         # over the night
NIGHT_FROM, NIGHT_TO = 18, 6


@dataclass
class Night:
    """The coming night (18:00 → 06:00) and the day before it."""

    starts: datetime
    temp: float              # average night air, °C
    cloud: int               # average cloud over the day and night, %
    wind: float              # average night wind, km/h
    rain: float              # night total, mm
    reasons: list = field(default_factory=list)
    level: str = "low"       # low | medium | high
    low_oxygen_ponds: list = field(default_factory=list)   # this morning's readings near the limit

    @property
    def is_risky(self):
        return self.level != "low"

    @property
    def tone(self):
        return {"high": "critical", "medium": "warn"}.get(self.level, "good")


def has_location(business):
    return business.latitude is not None and business.longitude is not None


def fetch(lat, lon):
    """Hourly forecast for two days, or None. Cached per place."""
    key = f"weather:{float(lat):.2f}:{float(lon):.2f}"
    data = cache.get(key)
    if data is not None:
        return data or None
    query = urlencode({"latitude": f"{float(lat):.4f}", "longitude": f"{float(lon):.4f}", "timezone": "auto", "forecast_days": 2,
                       "hourly": "temperature_2m,cloud_cover,wind_speed_10m,precipitation"})
    try:
        with urlopen(f"{URL}?{query}", timeout=TIMEOUT) as r:   # noqa: S310 — a fixed https address
            data = json.loads(r.read().decode("utf-8"))["hourly"]
    except Exception as e:  # network down, slow, or an odd answer: no forecast
        log.info("weather unavailable: %s", e)
        cache.set(key, {}, 15 * 60)    # don't ask again on every page for a while
        return None
    cache.set(key, data, KEEP)
    return data


def _night(hourly, now):
    """Pick the coming night out of the hourly lists."""
    hours = [datetime.fromisoformat(t) for t in hourly["time"]]
    today = now.date()
    start = datetime(today.year, today.month, today.day, NIGHT_FROM)
    if now.hour < NIGHT_TO:          # after midnight: the night we're in
        start -= timedelta(days=1)
    end = start + timedelta(hours=24 - NIGHT_FROM + NIGHT_TO)
    day_start = start - timedelta(hours=NIGHT_FROM - NIGHT_TO)   # 06:00 that day

    def pick(name, lo, hi):
        return [v for t, v in zip(hours, hourly[name]) if lo <= t < hi and v is not None]

    temp, wind, rain = pick("temperature_2m", start, end), pick("wind_speed_10m", start, end), pick("precipitation", start, end)
    cloud = pick("cloud_cover", day_start, end)
    if not (temp and wind and cloud):
        return None
    return Night(starts=start, temp=round(sum(temp) / len(temp), 1), cloud=round(sum(cloud) / len(cloud)),
                 wind=round(sum(wind) / len(wind), 1), rain=round(sum(rain), 1))


def assess(night, limits=None, oxygen_now=None):
    """Score the night. `oxygen_now`: [(pond, mg/L)] from this morning's tests."""
    score = 0
    if night.temp >= HOT_C:
        score += 1
        night.reasons.append(_("a hot night (%(t)s°C)") % {"t": night.temp})
    if night.cloud >= CLOUDY_PCT:
        score += 1
        night.reasons.append(_("cloudy (%(c)s%%), so little oxygen made in the day") % {"c": night.cloud})
    if night.wind <= STILL_KMH:
        score += 1
        night.reasons.append(_("little wind (%(w)s km/h)") % {"w": night.wind})
    if night.rain >= HEAVY_RAIN_MM:
        score += 1
        night.reasons.append(_("heavy rain (%(r)s mm)") % {"r": night.rain})
    if limits is not None and oxygen_now:
        edge = (limits.oxygen_min or Decimal(4)) + 1
        night.low_oxygen_ponds = [name for name, o in oxygen_now if o is not None and o < edge]
        if night.low_oxygen_ponds:
            score += 1
            night.reasons.append(_("oxygen already low this morning in %(ponds)s") % {"ponds": ", ".join(night.low_oxygen_ponds)})
    night.level = "high" if score >= 3 else "medium" if score == 2 else "low"
    return night


def _oxygen_this_morning(business, today):
    from .models import CycleStatus, WaterTest

    seen, out = set(), []
    for w in (WaterTest.objects.filter(business=business, cycle__status=CycleStatus.RUNNING, cycle__is_deleted=False,
                                       date__gte=today - timedelta(days=1), oxygen__isnull=False)
              .select_related("cycle__pond").order_by("-date", "-id")):
        if w.cycle_id not in seen:
            seen.add(w.cycle_id)
            out.append((w.cycle.pond.name, w.oxygen))
    return out


def tonight(business, now=None):
    """The coming night's risk for this farm, or None (no location, no forecast)."""
    if not has_location(business):
        return None
    hourly = fetch(business.latitude, business.longitude)
    if not hourly:
        return None
    now = now or timezone.localtime().replace(tzinfo=None)
    try:
        night = _night(hourly, now)
    except (KeyError, ValueError, TypeError) as e:
        log.info("weather answer not understood: %s", e)
        return None
    if night is None:
        return None
    from .models import PondAlerts

    return assess(night, PondAlerts.for_business(business), _oxygen_this_morning(business, now.date()))


def advice(night):
    """What to do about it, in a sentence."""
    if night.level == "high":
        return _("Run the aerators from midnight until after sunrise, feed less this evening, and check the fish at dawn — gulping at the surface means they need air now.")
    if night.level == "medium":
        return _("Keep the aerators ready for the early hours and watch the fish at dawn. Feed a little less this evening.")
    return _("Nothing special tonight.")
