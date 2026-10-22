"""An invoice (or a plain timesheet) from tracked time: for one project or one
client, between two dates — hours by project and task, × the project's rate.
Time put on an invoice is marked "billed", so it isn't billed twice."""
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from . import services
from .models import Project, TimeEntry

HOUR = Decimal(3600)


@dataclass
class Line:
    project: object
    task: object
    label: str
    seconds: int = 0
    entries: int = 0

    @property
    def hours(self):
        return (Decimal(self.seconds) / HOUR).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @property
    def rate(self):
        return self.project.hourly_rate if self.project else None

    @property
    def amount(self):
        return (self.hours * self.rate).quantize(Decimal("0.01"), ROUND_HALF_UP) if self.rate is not None else None


@dataclass
class Invoice:
    start: object
    end: object
    lines: list = field(default_factory=list)
    entry_ids: list = field(default_factory=list)
    already_billed: int = 0        # entries in range left out because they're on an earlier invoice

    @property
    def seconds(self):
        return sum(l.seconds for l in self.lines)

    @property
    def hours(self):
        return sum((l.hours for l in self.lines), Decimal(0))

    @property
    def total(self):
        return sum((l.amount for l in self.lines if l.amount is not None), Decimal(0))

    @property
    def unpriced(self):
        """Hours on projects with no rate — shown, not charged."""
        return sum((l.hours for l in self.lines if l.amount is None), Decimal(0))

    @property
    def projects(self):
        return list(OrderedDict((l.project.pk if l.project else None, l.project) for l in self.lines).values())


def build(user, start, end, project=None, client="", billable_only=True, include_billed=False):
    """The lines for an invoice. `project` (one) or `client` (all of its projects)."""
    lo, _x = services.day_bounds(start)
    _y, hi = services.day_bounds(end)
    qs = (TimeEntry.objects.filter(owner=user, started_at__gte=lo, started_at__lt=hi, ended_at__isnull=False)
          .select_related("project", "task").order_by("started_at"))
    if project is not None:
        qs = qs.filter(project=project)
    elif client:
        qs = qs.filter(project__client__iexact=client)
    if billable_only:
        qs = qs.filter(billable=True)
    inv = Invoice(start, end)
    if not include_billed:
        inv.already_billed = qs.filter(invoiced_at__isnull=False).count()
        qs = qs.filter(invoiced_at__isnull=True)
    lines = OrderedDict()
    for e in qs:
        key = (e.project_id, e.task_id or e.description.strip().lower())
        if key not in lines:
            lines[key] = Line(e.project, e.task, e.task.title if e.task_id else (e.description or str(e.project or "")))
        lines[key].seconds += e.seconds
        lines[key].entries += 1
        inv.entry_ids.append(e.pk)
    inv.lines = sorted(lines.values(), key=lambda l: ((l.project.name.lower() if l.project else "~"), -l.seconds))
    return inv


def mark_billed(user, ids):
    return TimeEntry.objects.filter(owner=user, pk__in=ids, invoiced_at__isnull=True).update(invoiced_at=timezone.now())


def clients(user):
    return sorted({c for c in Project.objects.filter(owner=user).exclude(client="").values_list("client", flat=True)}, key=str.lower)
