"""A cycle's targets, set at stocking, against how it is really going.

Targets: selling size, how many fish should survive, the FCR to aim for, the
price expected and a cost budget, with the cycle's expected harvest date.
From them: the fish to harvest, the feed it takes and the profit planned.
Each line then shows the plan, where the cycle stands, and whether that's on
track (good), slipping (warn) or well off (critical).
"""
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils.formats import date_format
from django.utils.translation import gettext as _

ZERO = Decimal(0)
USUAL_SURVIVAL = 80
USUAL_FCR = Decimal("1.6")


@dataclass
class Line:
    key: str
    label: str
    target: str
    now: str
    tone: str = ""       # good | warn | critical | "" (nothing to judge yet)
    note: str = ""


def has_targets(cycle):
    return any(getattr(cycle, f) is not None for f in ("target_size_g", "target_survival", "target_fcr", "target_price", "budget"))


def main_species(summary):
    rows = [r for r in summary.species if r.put_in]
    return max(rows, key=lambda r: r.put_in).species if rows else None


def planned_kg(cycle, summary):
    """Fish to harvest if the targets are met: fish put in × survival × size."""
    put_in = summary.stocked + summary.moved_in
    if not (put_in and cycle.target_survival and cycle.target_size_g):
        return None
    return (Decimal(put_in) * cycle.target_survival / 100 * cycle.target_size_g / 1000).quantize(Decimal("1"))


def planned_feed_kg(cycle, summary):
    kg = planned_kg(cycle, summary)
    if kg is None or not cycle.target_fcr:
        return None
    return max((kg - summary.stocked_kg) * cycle.target_fcr, ZERO).quantize(Decimal("1"))


def planned_profit(cycle, summary):
    kg = planned_kg(cycle, summary)
    if kg is None or cycle.target_price is None or cycle.budget is None:
        return None
    return (kg * cycle.target_price - cycle.budget).quantize(Decimal("1"))


def suggestions(cycle, summary, feed_price=None, usual_price=None):
    """Starting values for the targets form: the fish's own selling size, the
    usual survival and FCR, recent prices, and a budget from the fingerlings
    plus the feed the plan needs."""
    sp = main_species(summary)
    out = {"target_size_g": sp.market_size_g if sp else None, "target_survival": USUAL_SURVIVAL, "target_fcr": USUAL_FCR,
           "target_price": usual_price}
    put_in = summary.stocked + summary.moved_in
    if put_in and out["target_size_g"]:
        kg = Decimal(put_in) * USUAL_SURVIVAL / 100 * out["target_size_g"] / 1000
        feed = max(kg - summary.stocked_kg, ZERO) * USUAL_FCR
        if feed_price:
            budget = summary.stocking_cost + summary.moved_in_value + feed * feed_price
            out["budget"] = (budget * Decimal("1.1") / 1000).quantize(Decimal("1")) * 1000   # + 10% for care, labour…
    return out


def _tone_at_least(now, target, slack):
    if now >= target:
        return "good"
    return "warn" if now >= target - slack else "critical"


def _tone_at_most(now, target, slack):
    if now <= target:
        return "good"
    return "warn" if now <= target + slack else "critical"


def compare(cycle, summary, forecasts=(), wait=None, today=None):
    """[Line] for every target set. Empty if none are."""
    from apps.business.core.templatetags.business import bdt, num

    if not has_targets(cycle):
        return []
    today = today or date.today()
    running = cycle.is_running
    lines = []
    put_in = summary.stocked + summary.moved_in

    if cycle.target_survival and put_in:
        now = round(max(put_in - summary.died, 0) * 100 / put_in)
        lines.append(Line("survival", _("Fish surviving"), f"{cycle.target_survival}%", f"{now}%",
                          _tone_at_least(now, cycle.target_survival, 5),
                          _("%(n)s died so far") % {"n": num(summary.died)} if summary.died else ""))

    if cycle.target_fcr:
        fcr = summary.fcr_now
        if fcr:
            lines.append(Line("fcr", _("FCR"), num(cycle.target_fcr), ("≈ " if running else "") + num(fcr),
                              _tone_at_most(fcr, cycle.target_fcr, cycle.target_fcr * Decimal("0.1")),
                              _("lower is better")))
        else:
            lines.append(Line("fcr", _("FCR"), num(cycle.target_fcr), "—", "", _("weigh a sample to see it")))

    ready_on = None
    if cycle.target_size_g:
        grown = [f for f in forecasts if f.now_g]
        if grown:
            alive = sum(f.alive for f in grown)
            size = sum(Decimal(f.now_g) * f.alive for f in grown) / alive if alive else Decimal(grown[0].now_g)
            speed = [f.growth for f in grown if f.growth and f.growth > 0]
            note = ""
            tone = "good" if size >= cycle.target_size_g else ""
            if size < cycle.target_size_g and speed:
                avg = sum(speed) / len(speed)
                ready_on = today + timedelta(days=math.ceil((cycle.target_size_g - size) / avg))
                note = _("reaches it about %(date)s") % {"date": date_format(ready_on, "j M")}
                if cycle.expected_harvest:
                    late = (ready_on - cycle.expected_harvest).days
                    tone = "good" if late <= 7 else ("warn" if late <= 30 else "critical")
                    if late > 7:
                        note = _("reaches it about %(date)s — %(n)s days after the planned harvest") % {"date": date_format(ready_on, "j M"), "n": late}
            lines.append(Line("size", _("Fish size"), f"{num(cycle.target_size_g)} g", f"{num(size.quantize(Decimal('1')))} g", tone, note))
        elif not running and summary.harvest_kg:
            lines.append(Line("size", _("Fish size"), f"{num(cycle.target_size_g)} g", "—"))
        else:
            lines.append(Line("size", _("Fish size"), f"{num(cycle.target_size_g)} g", "—", "", _("weigh a sample to see it")))

    plan_kg = planned_kg(cycle, summary)
    expect_kg = None
    if plan_kg:
        if running:
            at_ready = [f.kg_at_ready for f in forecasts if f.kg_at_ready]
            expect_kg = (summary.harvest_kg + summary.moved_out_kg + sum(at_ready, ZERO)).quantize(Decimal("1")) if at_ready else None
        else:
            expect_kg = (summary.harvest_kg + summary.moved_out_kg).quantize(Decimal("1"))
        if expect_kg is not None:
            pct = expect_kg * 100 / plan_kg
            lines.append(Line("harvest", _("Fish to harvest"), f"{num(plan_kg)} kg", ("≈ " if running else "") + f"{num(expect_kg)} kg",
                              "good" if pct >= 95 else ("warn" if pct >= 80 else "critical"),
                              _("at selling size, with the fish alive now") if running else _("harvested")))
        else:
            lines.append(Line("harvest", _("Fish to harvest"), f"{num(plan_kg)} kg", "—", "", _("weigh a sample to see it")))

    if cycle.budget is not None:
        spent = summary.cost
        note, tone = "", ""
        if cycle.budget:
            pct = round(spent * 100 / cycle.budget)
            if running and cycle.expected_harvest and cycle.expected_harvest > cycle.start_date:
                time_pct = min(round((today - cycle.start_date).days * 100 / (cycle.expected_harvest - cycle.start_date).days), 100)
                note = _("%(spent)s%% spent, %(time)s%% of the time gone") % {"spent": pct, "time": time_pct}
                tone = "good" if pct <= time_pct + 10 else ("warn" if pct <= 100 else "critical")
            else:
                note = _("%(spent)s%% of the budget") % {"spent": pct}
                tone = "good" if pct <= 100 else ("warn" if pct <= 110 else "critical")
        lines.append(Line("cost", _("Cost"), bdt(cycle.budget), bdt(spent), tone, note))

    plan_profit = planned_profit(cycle, summary)
    if plan_profit is not None:
        if running:
            expect = None
            if expect_kg is not None and cycle.target_price is not None:
                still = expect_kg - summary.harvest_kg - summary.moved_out_kg
                extra = wait.more_cost if wait else ZERO
                expect = (summary.earned + still * cycle.target_price - summary.cost - extra).quantize(Decimal("1"))
            if expect is None:
                lines.append(Line("profit", _("Profit"), bdt(plan_profit), "—", "", _("weigh a sample to see it")))
            else:
                diff = expect - plan_profit
                lines.append(Line("profit", _("Profit"), bdt(plan_profit), "≈ " + bdt(expect),
                                  "good" if diff >= 0 else ("warn" if diff >= -abs(plan_profit) * Decimal("0.2") else "critical"),
                                  _("at the expected price, once the fish reach selling size")))
        else:
            diff = summary.profit - plan_profit
            lines.append(Line("profit", _("Profit"), bdt(plan_profit), bdt(summary.profit),
                              "good" if diff >= 0 else ("warn" if diff >= -abs(plan_profit) * Decimal("0.2") else "critical")))
    return lines
