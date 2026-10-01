"""Build static/css/tailwind.css with Tailwind's standalone program (no Node or npm).

    python manage.py tailwind            build once, minified
    python manage.py tailwind --watch    rebuild on every template change
    python manage.py tailwind --check    fail if the built file is out of date (for CI)

The pages used to load Tailwind's in-browser compiler, which rebuilt this same
CSS on every page load on the phone itself (about a second of CPU on a mid-range
Android). The program is downloaded once into a cache folder outside the project.
"""
import os
import platform
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

VERSION = "3.4.17"     # the same version the old CDN script served, so the CSS is identical
URL = "https://github.com/tailwindlabs/tailwindcss/releases/download/v{version}/{asset}"


def _asset():
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "linux":
        return f"tailwindcss-linux-{arch}"
    if system == "darwin":
        return f"tailwindcss-macos-{arch}"
    if system == "windows":
        return "tailwindcss-windows-x64.exe"
    raise CommandError(f"No Tailwind program for {system} {machine}.")


def _binary(stdout):
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fintrack"
    path = cache / f"{VERSION}-{_asset()}"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        url = URL.format(version=VERSION, asset=_asset())
        stdout.write(f"Downloading Tailwind {VERSION} (once) …")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Command(BaseCommand):
    help = "Build static/css/tailwind.css from the templates."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Rebuild whenever a template changes.")
        parser.add_argument("--check", action="store_true", help="Exit with an error if tailwind.css is out of date.")

    def handle(self, *args, watch=False, check=False, **options):
        base = Path(settings.BASE_DIR)
        config, source = base / "tailwind.config.js", base / "static" / "src" / "tailwind.css"
        output = base / "static" / "css" / "tailwind.css"
        target = Path(tempfile.mkstemp(suffix=".css")[1]) if check else output
        cmd = [str(_binary(self.stdout)), "-c", str(config), "-i", str(source), "-o", str(target), "--minify"]
        if watch:
            cmd.append("--watch")
        result = subprocess.run(cmd, cwd=base, capture_output=not watch, text=True)
        if result.returncode != 0:
            raise CommandError((result.stderr or "Tailwind failed.").strip())
        if check:
            same = target.read_bytes() == output.read_bytes() if output.exists() else False
            target.unlink(missing_ok=True)
            if not same:
                self.stderr.write("static/css/tailwind.css is out of date. Run: python manage.py tailwind")
                sys.exit(1)
            self.stdout.write(self.style.SUCCESS("tailwind.css is up to date."))
            return
        self.stdout.write(self.style.SUCCESS(f"Built {output.relative_to(base)} ({output.stat().st_size // 1024} KB)."))
