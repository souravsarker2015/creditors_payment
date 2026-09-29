"""Water readings against the farm's own alert levels (see PondAlerts)."""
from dataclasses import dataclass

from django.utils.translation import gettext as _


@dataclass
class Problem:
    reading: str      # oxygen | ph | temperature | ammonia | transparency
    what: str         # "Oxygen low: 3.1 mg/L (warn below 4)"
    todo: str         # what usually helps
    urgent: bool = False


def _n(v):
    return format(v.normalize(), "f")


def check(test, limits):
    out = []
    if test.oxygen is not None and test.oxygen < limits.oxygen_min:
        out.append(Problem("oxygen", _("Oxygen low: %(v)s mg/L (warn below %(l)s)") % {"v": _n(test.oxygen), "l": _n(limits.oxygen_min)},
                           _("Run the aerator or add fresh water, and feed less until it recovers. Fish gasping at the surface at dawn is a sign."),
                           urgent=True))
    if test.ph is not None and test.ph < limits.ph_min:
        out.append(Problem("ph", _("pH low: %(v)s (warn below %(l)s)") % {"v": _n(test.ph), "l": _n(limits.ph_min)},
                           _("Water is too acidic. Liming usually brings it up.")))
    if test.ph is not None and test.ph > limits.ph_max:
        out.append(Problem("ph", _("pH high: %(v)s (warn above %(l)s)") % {"v": _n(test.ph), "l": _n(limits.ph_max)},
                           _("Don't add lime now. Adding fresh water helps; check again in the early morning.")))
    if test.temperature is not None and test.temperature < limits.temperature_min:
        out.append(Problem("temperature", _("Water cold: %(v)s °C (warn below %(l)s)") % {"v": _n(test.temperature), "l": _n(limits.temperature_min)},
                           _("Fish eat less in cold water. Feed less so feed isn't wasted.")))
    if test.temperature is not None and test.temperature > limits.temperature_max:
        out.append(Problem("temperature", _("Water hot: %(v)s °C (warn above %(l)s)") % {"v": _n(test.temperature), "l": _n(limits.temperature_max)},
                           _("Hot water holds less oxygen. Feed in the cool of the morning and watch the oxygen.")))
    if test.ammonia is not None and test.ammonia > limits.ammonia_max:
        out.append(Problem("ammonia", _("Ammonia high: %(v)s mg/L (warn above %(l)s)") % {"v": _n(test.ammonia), "l": _n(limits.ammonia_max)},
                           _("Feed less and add fresh water. Uneaten feed and waste raise ammonia."), urgent=True))
    if test.transparency is not None and test.transparency < limits.transparency_min:
        out.append(Problem("transparency", _("Water too green or muddy: %(v)s cm (warn below %(l)s)") % {"v": _n(test.transparency), "l": _n(limits.transparency_min)},
                           _("Too much plankton or mud. Hold back on fertiliser and add fresh water if you can.")))
    if test.transparency is not None and test.transparency > limits.transparency_max:
        out.append(Problem("transparency", _("Water too clear: %(v)s cm (warn above %(l)s)") % {"v": _n(test.transparency), "l": _n(limits.transparency_max)},
                           _("Too little natural food (plankton) in the water.")))
    return out
