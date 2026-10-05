from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, Sum

from .models import Condition, Equipment, Service

ZERO = Decimal(0)
SOON_DAYS = 7


def with_service_dates(objects):
    """Adds .last_service and .next_due to each machine (one query for all)."""
    last = dict(Service.objects.filter(equipment__in=objects).values_list("equipment_id").annotate(d=Max("date")))
    spent = dict(Service.objects.filter(equipment__in=objects).values_list("equipment_id").annotate(t=Sum("cost")))
    today = date.today()
    for e in objects:
        e.last_service = last.get(e.pk)
        e.next_due = e.next_service(e.last_service)
        e.upkeep = spent.get(e.pk) or ZERO
        e.due_in = (e.next_due - today).days if e.next_due else None
    return objects


def needs_attention(business, today=None):
    """Machines that are broken, or due for a service within a week."""
    today = today or date.today()
    items = with_service_dates(list(Equipment.objects.filter(business=business).exclude(condition=Condition.OUT)))
    broken = [e for e in items if e.condition == Condition.REPAIR]
    due = [e for e in items if e.condition == Condition.WORKING and e.next_due and e.next_due <= today + timedelta(days=SOON_DAYS)]
    return broken, sorted(due, key=lambda e: e.next_due)


def costs(business, start, end):
    """(bought, upkeep) between two dates."""
    bought = Equipment.all_objects.filter(business=business, is_deleted=False, bought_on__gte=start, bought_on__lte=end).aggregate(t=Sum("cost"))["t"] or ZERO
    upkeep = Service.objects.filter(business=business, date__gte=start, date__lte=end).aggregate(t=Sum("cost"))["t"] or ZERO
    return bought, upkeep
