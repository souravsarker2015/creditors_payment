"""python manage.py backup_export [file.zip] — the whole system in one backup file
(the same file as "Download backup" on the Backup & restore page)."""
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core import backup as bk


class Command(BaseCommand):
    help = "Write a backup of the whole system (all data and uploaded files) to a .zip file."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="Where to write it (default: a dated file in BACKUP_DIR).")

    def handle(self, *args, path=None, **options):
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            manifest = bk.write_backup(target)
        else:
            target = bk.save_on_server()
            manifest = bk.read_backup(target).manifest
        media = len(manifest["files"]) - 1
        self.stdout.write(self.style.SUCCESS(f"Backup written: {target}  ({manifest['total']} records, {media} files)"))
