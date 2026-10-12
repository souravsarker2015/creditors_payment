from datetime import date

from django.core.management.base import BaseCommand

from apps.business.core import summary


class Command(BaseCommand):
    help = ("Email the evening summary to everyone who turned it on. Run it once every evening, e.g. a "
            "PythonAnywhere scheduled task at 20:00 (Asia/Dhaka). Safe to run again: each person gets each day once.")

    def add_arguments(self, parser):
        parser.add_argument("--date", help="The day to summarise (YYYY-MM-DD). Default: today after 8 pm, else yesterday.")

    def handle(self, *args, **opts):
        day = date.fromisoformat(opts["date"]) if opts.get("date") else summary.due_day()
        sent = failed = 0
        for m in summary.pending(day=day):
            if not m.user.is_active:
                continue
            if summary.send(m, day):
                sent += 1
            else:
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"{day}: sent {sent}") + (f", {failed} failed" if failed else ""))
