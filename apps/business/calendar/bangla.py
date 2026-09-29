"""The Bangla calendar (Bangabda) as used in Bangladesh, and Bangla numerals.

Bangladesh follows the Bangla Academy's revised calendar (2019 revision):
Boishakh–Ashwin have 31 days, Kartik–Magh and Chaitra 30, and Falgun 29
(30 in a Gregorian leap year). So every Bangla date falls on the same English
date each year — 1 Boishakh is always 14 April, 8 Falgun is 21 February,
12 Chaitra is 26 March and 1 Poush is 16 December.
"""
from dataclasses import dataclass
from datetime import date, timedelta

# (English month, day) on which each Bangla month starts, from Boishakh.
MONTH_STARTS = [(4, 14), (5, 15), (6, 15), (7, 16), (8, 16), (9, 16), (10, 17), (11, 16), (12, 16), (1, 15), (2, 14), (3, 15)]
YEAR_OFFSET = 593   # 14 April 2026 starts 1433

MONTHS_BN = ["বৈশাখ", "জ্যৈষ্ঠ", "আষাঢ়", "শ্রাবণ", "ভাদ্র", "আশ্বিন", "কার্তিক", "অগ্রহায়ণ", "পৌষ", "মাঘ", "ফাল্গুন", "চৈত্র"]
MONTHS_EN = ["Boishakh", "Joishtho", "Asharh", "Srabon", "Bhadro", "Ashwin", "Kartik", "Ogrohayon", "Poush", "Magh", "Falgun", "Choitro"]

# Six seasons of two months each, starting with Boishakh.
SEASONS_BN = ["গ্রীষ্ম", "বর্ষা", "শরৎ", "হেমন্ত", "শীত", "বসন্ত"]
SEASONS_EN = ["Summer", "Monsoon", "Autumn", "Late autumn", "Winter", "Spring"]

WEEKDAYS_BN = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"]     # Monday first, like date.weekday()
WEEKDAYS_BN_SHORT = ["সোম", "মঙ্গল", "বুধ", "বৃহঃ", "শুক্র", "শনি", "রবি"]
GREGORIAN_BN = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]

_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn_digits(value):
    """'2026' → '২০২৬'. Works on any text; only the digits change."""
    return str(value).translate(_DIGITS)


@dataclass(frozen=True)
class BanglaDate:
    year: int
    month: int      # 1 = Boishakh … 12 = Choitro
    day: int

    @property
    def season(self):
        return (self.month - 1) // 2          # 0 = summer … 5 = spring

    def name(self, bangla=True):
        return MONTHS_BN[self.month - 1] if bangla else MONTHS_EN[self.month - 1]

    def season_name(self, bangla=True):
        return SEASONS_BN[self.season] if bangla else SEASONS_EN[self.season]

    def format(self, bangla=True, year=True):
        """'১৪ আশ্বিন ১৪৩৩' or '14 Ashwin 1433'."""
        text = f"{self.day} {self.name(bangla)}" + (f" {self.year}" if year else "")
        return bn_digits(text) if bangla else text


def _starts(year):
    """The English date each month of Bangla `year` begins on."""
    g = year + YEAR_OFFSET
    return [date(g if i < 9 else g + 1, m, d) for i, (m, d) in enumerate(MONTH_STARTS)]


def to_bangla(d):
    """The Bangla date for an English date."""
    year = d.year - YEAR_OFFSET if (d.month, d.day) >= (4, 14) else d.year - YEAR_OFFSET - 1
    starts = _starts(year)
    month = max(i for i, s in enumerate(starts) if s <= d)
    return BanglaDate(year, month + 1, (d - starts[month]).days + 1)


def month_bounds(year, month):
    """(first day, last day) in English dates of a Bangla month."""
    starts = _starts(year)
    first = starts[month - 1]
    last = (starts[month] if month < 12 else _starts(year + 1)[0]) - timedelta(days=1)
    return first, last


def month_length(year, month):
    first, last = month_bounds(year, month)
    return (last - first).days + 1


def from_bangla(year, month, day):
    """The English date for a Bangla date. Raises ValueError if it doesn't exist."""
    if not 1 <= month <= 12:
        raise ValueError("month")
    if not 1 <= day <= month_length(year, month):
        raise ValueError("day")
    return month_bounds(year, month)[0] + timedelta(days=day - 1)


def add_bangla_months(year, month, n):
    total = year * 12 + (month - 1) + n
    return total // 12, total % 12 + 1
