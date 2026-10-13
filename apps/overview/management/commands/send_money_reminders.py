from datetime import date

from django.core.management.base import BaseCommand

from apps.overview import reminders


class Command(BaseCommand):
    help = ("Email the morning money reminder to everyone who turned it on. Run it once every morning, e.g. a "
            "PythonAnywhere scheduled task at 07:00 (Asia/Dhaka). Safe to run again: each person gets one a day, "
            "and none on a day with nothing late or due soon.")

    def add_arguments(self, parser):
        parser.add_argument("--date", help="The day to remind about (YYYY-MM-DD). Default: today.")

    def handle(self, *args, **opts):
        today = date.fromisoformat(opts["date"]) if opts.get("date") else None
        counts = {"sent": 0, "nothing": 0, "failed": 0}
        for user in reminders.pending(today):
            counts[reminders.send(user, today)] += 1
        self.stdout.write(self.style.SUCCESS(
            f"sent {counts['sent']}, nothing to say {counts['nothing']}") + (f", {counts['failed']} failed" if counts["failed"] else ""))
