"""python manage.py backup_restore file.zip — replace all data with a backup's
(the same as restoring on the Backup & restore page)."""
from django.core.management.base import BaseCommand, CommandError

from apps.core import backup as bk


class Command(BaseCommand):
    help = "Replace ALL data with the contents of a backup file. The current data is saved to BACKUP_DIR first."

    def add_arguments(self, parser):
        parser.add_argument("path", help="The backup .zip file.")
        parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation.")
        parser.add_argument("--no-copy", action="store_true", help="Don't save the current data first.")

    def handle(self, *args, path, yes=False, no_copy=False, **options):
        try:
            backup = bk.read_backup(path)
        except (bk.BackupError, OSError) as exc:
            raise CommandError(str(exc))
        m = backup.manifest
        now = sum(bk.current_counts().values())
        self.stdout.write(f"Backup made {m['created_at']} by {m.get('created_by') or '-'}: {m['total']} records, {len(backup.media)} files.")
        self.stdout.write(f"This system has {now} records now. Admins in the backup: {', '.join(backup.admins)}")
        for note in backup.notes:
            self.stdout.write(note)
        if not yes and input("Replace ALL current data with this backup? Type 'yes': ").strip().lower() != "yes":
            raise CommandError("Cancelled. Nothing was changed.")
        try:
            result = bk.restore_backup(backup, keep_copy=not no_copy)
        except bk.BackupError as exc:
            raise CommandError(str(exc))
        if result["safety_copy"]:
            self.stdout.write(f"The data from before was saved as {result['safety_copy']}")
        self.stdout.write(self.style.SUCCESS(f"Restored {sum(result['counts'].values())} records. Everyone signs in again."))
