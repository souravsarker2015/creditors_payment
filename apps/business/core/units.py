"""Unit conversion and the starter set of units."""
from decimal import Decimal

from .models import Unit, UnitType

# name, Bangla, symbol, type, factor (in the type's base unit), base?
DEFAULT_UNITS = [
    ("Kilogram", "কেজি", "kg", UnitType.WEIGHT, "1", True),
    ("Gram", "গ্রাম", "g", UnitType.WEIGHT, "0.001", False),
    ("Mon (maund)", "মণ", "mon", UnitType.WEIGHT, "40", False),
    ("Quintal", "কুইন্টাল", "qtl", UnitType.WEIGHT, "100", False),
    ("Ton", "টন", "ton", UnitType.WEIGHT, "1000", False),
    ("Piece", "পিস", "pcs", UnitType.COUNT, "1", True),
    ("Hali (4)", "হালি", "hali", UnitType.COUNT, "4", False),
    ("Dozen", "ডজন", "doz", UnitType.COUNT, "12", False),
    ("Hundred (sho)", "শ", "sho", UnitType.COUNT, "100", False),
    ("Thousand (hajar)", "হাজার", "hajar", UnitType.COUNT, "1000", False),
    ("Litre", "লিটার", "L", UnitType.VOLUME, "1", True),
    ("Millilitre", "মিলি", "ml", UnitType.VOLUME, "0.001", False),
    ("Decimal", "শতাংশ", "dec", UnitType.AREA, "1", True),
    ("Katha", "কাঠা", "katha", UnitType.AREA, "1.65", False),
    ("Bigha", "বিঘা", "bigha", UnitType.AREA, "33", False),
    ("Acre", "একর", "acre", UnitType.AREA, "100", False),
    ("General unit", "একক", "unit", UnitType.OTHER, "1", True),
]


def seed_units(business, mon_kg=None):
    """Add any missing standard units. Safe to run again: existing units
    (including edited factors) are left alone. Returns how many were added."""
    from .audit import audit_paused

    have = set(Unit.all_objects.filter(business=business).values_list("symbol", flat=True))
    added = 0
    with audit_paused():
        added = _add_missing(business, have, mon_kg)
    return added


def _add_missing(business, have, mon_kg):
    added = 0
    for order, (name, name_bn, symbol, unit_type, factor, is_base) in enumerate(DEFAULT_UNITS):
        if symbol in have:
            continue
        value = Decimal(str(mon_kg)) if symbol == "mon" and mon_kg else Decimal(factor)
        Unit.all_objects.create(business=business, name=name, name_bn=name_bn, symbol=symbol,
                                unit_type=unit_type, factor=value, is_base=is_base, order=order)
        added += 1
    return added


class ConversionError(ValueError):
    pass


def to_base(quantity, unit):
    return Decimal(quantity) * unit.factor


def convert(quantity, from_unit, to_unit):
    """5 mon → 200 kg. Only between units that measure the same thing."""
    if from_unit.unit_type != to_unit.unit_type:
        raise ConversionError(f"Can't convert {from_unit.symbol} ({from_unit.unit_type}) to {to_unit.symbol} ({to_unit.unit_type}).")
    return Decimal(quantity) * from_unit.factor / to_unit.factor
