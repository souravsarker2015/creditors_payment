from django.core.management.base import BaseCommand

from apps.business.core.models import Business
from apps.business.core.units import seed_units


class Command(BaseCommand):
    help = "Add the standard starter data (units; species and categories in later phases) to every business, or one with --business. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--business", type=int, help="Only this business id.")

    def handle(self, *args, **opts):
        qs = Business.objects.all()
        if opts.get("business"):
            qs = qs.filter(pk=opts["business"])
        for b in qs:
            added = seed_units(b)
            self.stdout.write(f"{b.name}: {added} unit(s) added")
        self.stdout.write(self.style.SUCCESS("Done."))
