"""Starter data every new farm gets (units, species, categories…).

Each business app registers a seeder in its AppConfig.ready(); seeders must be
idempotent (only add what's missing) and return how many rows they added.
create_business() and `manage.py seed_business` run them all.
"""
from .audit import audit_paused

SEEDERS = []   # (label, fn(business) -> int)


def register(label, fn):
    if all(existing != label for existing, _ in SEEDERS):
        SEEDERS.append((label, fn))


def seed_all(business):
    added = {}
    with audit_paused():
        for label, fn in SEEDERS:
            added[label] = fn(business)
    return added
