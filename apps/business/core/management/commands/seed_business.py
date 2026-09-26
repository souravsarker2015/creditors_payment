from django.core.management.base import BaseCommand

from apps.business.core.models import Business
from apps.business.core.seeding import seed_all


class Command(BaseCommand):
    help = "Add the standard starter data (units, species, categories, deduction types, a cash account) to every business, or one with --business. Safe to re-run: only what's missing is added."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, help="Only this business id.")

    def handle(self, *args, **opts):
        qs = Business.objects.all()
        if opts.get("business"):
            qs = qs.filter(pk=opts["business"])
        for b in qs:
            added = seed_all(b)
            summary = ", ".join(f"{n} {label}" for label, n in added.items())
            self.stdout.write(f"{b.name}: added {summary or 'nothing'}")
        self.stdout.write(self.style.SUCCESS("Done."))
