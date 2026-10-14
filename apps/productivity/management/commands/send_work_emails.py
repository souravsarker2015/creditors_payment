from django.core.management.base import BaseCommand

from apps.productivity import emails


class Command(BaseCommand):
    help = ("Productivity emails for people who turned them on: \"Your day\" when each person's work day starts, and "
            "task reminders whose time has come. Run it every hour (e.g. a PythonAnywhere scheduled task); every 15 "
            "minutes keeps reminders closer to their time. Safe to run again: nothing is sent twice.")

    def handle(self, *args, **opts):
        c = emails.run()
        self.stdout.write(self.style.SUCCESS(
            f"your day: {c['briefs']} sent, {c['quiet']} with nothing to say · reminders: {c['reminders']} sent")
            + (f" · {c['failed']} failed" if c["failed"] else ""))
