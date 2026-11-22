"""Bringing a backup made before an update up to date, so it can still be restored.

A backup can only be restored on a server whose updates since then only *added*
things (backup._check_version). An update that changed existing data refuses
older backups — unless it is listed in UPGRADES with a step that does the same
change to the backup's records, in memory, before they are loaded.

Each step gets the backup (manifest, rows) and changes its rows and counts.
"""
from importlib import import_module

from django.utils import timezone

# (app, migration) -> "module.function"
UPGRADES = {
    ("creditors", "0013_creditor_categories"): "apps.core.backup_upgrades.creditor_categories",
    ("debtors", "0009_debtor_categories"): "apps.core.backup_upgrades.debtor_categories",
    ("shops", "0008_shop_categories"): "apps.core.backup_upgrades.shop_categories",
    ("contributors", "0007_contributor_categories"): "apps.core.backup_upgrades.contributor_categories",
}


def run(backup, key):
    module, name = UPGRADES[key].rsplit(".", 1)
    getattr(import_module(module), name)(backup)


def _person_categories(backup, *, person, category, starters):
    """Before: each person had a code ("FAMILY"). After: a link to a row of their own category list.
    The same as the migration: every user gets the starters; each person is linked to the one of their code."""
    from django.conf import settings

    user_label = settings.AUTH_USER_MODEL.lower()
    rows = backup.rows
    people = [r for r in rows if r.get("model") == person]
    users = [r["pk"] for r in rows if r.get("model") == user_label]           # the whole system: every account
    for r in people:                                                           # one person's backup: theirs
        uid = r["fields"].get("user")
        if uid is not None and uid not in users:
            users.append(uid)
    taken = [r["pk"] for r in rows if r.get("model") == category and isinstance(r.get("pk"), int)]
    next_pk = max(taken, default=0) + 1
    now = timezone.now().isoformat()
    names = dict(starters)
    made, added = {}, []

    def add(uid, code, name):
        nonlocal next_pk
        added.append({"model": category, "pk": next_pk,
                      "fields": {"user": uid, "name": name, "code": code, "is_active": True, "created_at": now}})
        made[(uid, code)] = next_pk
        next_pk += 1

    for uid in users:
        for code, name in starters:
            add(uid, code, name)
    for r in people:
        value = r["fields"].get("category")
        if isinstance(value, int) or (value is None and "category" not in r["fields"]):
            continue                                   # already a link (or nothing to change)
        uid, code = r["fields"].get("user"), value or "OTHER"
        if (uid, code) not in made:                    # a value the fixed list never had: kept, as its own category
            add(uid, code, names.get(code) or str(code).replace("_", " ").title()[:80])
        r["fields"]["category"] = made[(uid, code)]
    rows.extend(added)
    counts = backup.manifest.setdefault("counts", {})
    counts[category] = counts.get(category, 0) + len(added)
    if "total" in backup.manifest:
        backup.manifest["total"] = backup.manifest["total"] + len(added)


def creditor_categories(backup):
    starters = import_module("apps.creditors.migrations.0013_creditor_categories").STARTERS
    _person_categories(backup, person="creditors.creditor", category="creditors.creditorcategory", starters=starters)


def debtor_categories(backup):
    starters = import_module("apps.debtors.migrations.0009_debtor_categories").STARTERS
    _person_categories(backup, person="debtors.debtor", category="debtors.debtorcategory", starters=starters)


def shop_categories(backup):
    starters = import_module("apps.shops.migrations.0008_shop_categories").STARTERS
    _person_categories(backup, person="shops.shop", category="shops.shopcategory", starters=starters)


def contributor_categories(backup):
    starters = import_module("apps.contributors.migrations.0007_contributor_categories").STARTERS
    _person_categories(backup, person="contributors.contributor", category="contributors.contributorcategory", starters=starters)
