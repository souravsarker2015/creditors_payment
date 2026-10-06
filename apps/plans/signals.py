"""Every payment recorded on a ledger with a plan moves its next due date."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.creditors.models import Transaction as CreditorTx
from apps.debtors.models import Transaction as DebtorTx
from apps.shops.models import Transaction as ShopTx


def _sync(party):
    plan = getattr(party, "plan", None) if party is not None else None
    if plan is not None:
        from .services import sync_due_date

        sync_due_date(plan)


def _resolve(get_party):
    try:
        return get_party()
    except Exception:  # the ledger itself is being deleted
        return None


@receiver([post_save, post_delete], sender=CreditorTx)
def _creditor_changed(sender, instance, **kwargs):
    _sync(_resolve(lambda: instance.creditor))


@receiver([post_save, post_delete], sender=DebtorTx)
def _debtor_changed(sender, instance, **kwargs):
    _sync(_resolve(lambda: instance.debtor))


@receiver([post_save, post_delete], sender=ShopTx)
def _shop_changed(sender, instance, **kwargs):
    _sync(_resolve(lambda: instance.shop))
