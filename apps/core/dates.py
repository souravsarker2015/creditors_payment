"""Dates from an address or a request: one that can't be a date (2026-13-45) is no date, not an error page."""
from django.utils import dateparse


def parse_date(value):
    try:
        return dateparse.parse_date(value)
    except (TypeError, ValueError):
        return None


def parse_datetime(value):
    try:
        return dateparse.parse_datetime(value)
    except (TypeError, ValueError):
        return None
