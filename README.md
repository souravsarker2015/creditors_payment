# Creditors Payment

A Django-based creditors payment management system.

## Quick Start

```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements/dev.txt

# 3. Run migrations
python manage.py migrate

# 4. Create a superuser
python manage.py createsuperuser

# 5. Start the development server
python manage.py runserver
```

## Front end

Pages are rendered by Django, with three small layers on top:

- **Tailwind CSS is prebuilt** into `static/css/tailwind.css` (committed). After adding or changing
  Tailwind classes in a template, rebuild it — no Node or npm needed:

  ```bash
  python manage.py tailwind          # build once
  python manage.py tailwind --watch  # rebuild while you edit templates
  python manage.py tailwind --check  # in CI: fails if the file is out of date
  ```

  The first run downloads Tailwind's standalone program (v3.4.17) into `~/.cache/fintrack/`.
- **Alpine.js** handles small interactions inside a page (menus, pop-ups, live totals).
- **HTMX** makes search boxes and filters update only the list, without reloading the page. A list
  page opts in with `{% include "partials/live_search.html" %}` inside its search `<form>` and an
  element with `id="results"` around the list.
- **Instant page changes**: `templates/base.html` holds Speculation Rules (the next page loads while
  a link is being pressed) and cross-fade View Transitions. Links with `?…`, logout, admin and
  downloads are never fetched ahead; mark any other link that changes something on a GET with
  `data-no-prefetch`.
- **App view on phones**: each person picks *Automatic* (app view when FinTrack is opened from its
  home-screen icon), *App view* or *Website view* — in the "More" sheet, the top-bar menu or the
  phone sidebar. App view adds a bottom tab bar, a "+" sheet of quick actions and a "More" sheet
  (`templates/partials/app_shell.html`); its styles are under "App view" in `static/css/app.css`.
  The menu sections live in `templates/partials/nav_sections.html`, shared by the sidebar and the
  "More" sheet, so a new page added there appears in both.

## Backup & restore (moving to another server)

Site admins (superusers) have **Backup & restore** in the account menu (`/backup/`). A backup is one
`.zip` file: every row of every table as JSON (ids kept), the uploaded photos and receipts, and a
manifest with record counts, the app version (migrations) and a SHA-256 for every file. It loads into
SQLite or PostgreSQL alike.

Restoring **replaces** all data with the backup's (it never merges, so nothing is duplicated) in one
transaction: the file is checked first (checksums, version, at least one admin account), then every
link between records and every table's count is verified before it commits — otherwise nothing
changes. The current data is saved to `BACKUP_DIR` (default `backups/`, ignored by git) first, and
everyone signs in again afterwards.

```bash
python manage.py backup_export [file.zip]     # same file as "Download backup"
python manage.py backup_restore file.zip      # asks for confirmation; --yes to skip
```

To move servers: download a backup on the old one; on the new one run `migrate` and
`createsuperuser` (a temporary admin), sign in, and restore the file. Sign in with your usual account.

## Project Structure

```
creditors_payment/
├── config/              # Project configuration (settings, URLs, WSGI/ASGI)
│   └── settings/
│       ├── base.py      # Shared settings
│       ├── dev.py       # Development overrides
│       └── prod.py      # Production overrides
├── apps/                # Django applications
├── templates/           # Project-wide HTML templates
├── static/              # Project-wide static files (CSS, JS, images)
├── media/               # User-uploaded files
├── requirements/        # Dependency files
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt
└── manage.py
```

## Creating a New App

```bash
# Create the app inside the apps/ directory
cd apps
python ../manage.py startapp <app_name>
```

Then add `"apps.<app_name>"` to `LOCAL_APPS` in `config/settings/base.py`.

## Environment Settings

- **Development** (default): `config.settings.dev` — SQLite, DEBUG=True
- **Production**: `config.settings.prod` — PostgreSQL, DEBUG=False
- **Live on PythonAnywhere**: `config.settings.live` — SQLite, DEBUG=False

Switch by setting `DJANGO_SETTINGS_MODULE`:

```bash
export DJANGO_SETTINGS_MODULE=config.settings.prod
```
## Personal API and the `ft` command

Productivity → Settings → API makes a token. Only its hash is kept, and personal backups never carry it.

```bash
curl -fsSL https://your-site/work/cli/ft -o ~/.local/bin/ft && chmod +x ~/.local/bin/ft
ft login                            # paste the token (or set FT_TOKEN)
ft add "fix(auth): login loop p1"
ft start T-42
ft stop "next: check the retry"     # where you left off
git switch -c $(ft branch T-42)
ft hook                             # in a repository: commits name the task of their branch
ft help
```

The API is under `/work/api/v1/` with `Authorization: Bearer <token>`: `GET /me/`, `GET|POST /tasks/`, `GET|POST /tasks/T-42/`,
`GET|POST /timer/`, `POST /log/`, `GET /snippets/`, `GET /standup/`. Answers are JSON, or plain lines with `Accept: text/plain`.

## Going live on PythonAnywhere

`config.settings.dev` must never serve the public site: with DEBUG on, an error page shows your code and settings to
anyone. Back up `db.sqlite3` first, then:

1. Add a secret key of its own to `.env` on the server (the one in `base.py` is public). Get one with:
   `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`
   ```bash
   DJANGO_SECRET_KEY=the-long-random-value
   ```
2. In the Web tab → WSGI configuration file, set
   `os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.live"`
3. Run `python manage.py collectstatic --noinput --settings=config.settings.live` if `/static/` points at `staticfiles`.
4. In the Web tab → Static files, remove any mapping for `/media/`. Receipts, memos, papers and pond photos are served
   by the app to the people allowed to see them; a `/media/` mapping would put them on the open internet.
5. Reload the web app. Everyone is signed out once, because the key changed.

Errors and pages not found now go to the site's error log (Web tab → Log files).

### Each update after that

Back up `db.sqlite3` first (`python manage.py backup_export --keep 14`), then in the Bash console:

```bash
git pull
pip install -r requirements/base.txt
python manage.py migrate --settings=config.settings.live
python manage.py collectstatic --noinput --settings=config.settings.live
```

Then reload the web app. Skip `pip install` only when `requirements/` hasn't changed.

If the browser says "too many redirects", add `DJANGO_SECURE_SSL_REDIRECT=False` to `.env`, turn on **Force HTTPS** in the
Web tab, and reload.

While a public site is still in debug mode, or on the public secret key, site admins see a red warning on every page.

Anyone can create an account until a site admin turns that off under Account & security → *Anyone can create an account*.

To undo: put `config.settings.dev` back in the WSGI file and reload.

## Secrets and email (`.env`)

Secrets go in a `.env` file at the project root (git-ignored; copy `.env.example`).
Real environment variables win over it. The Gmail settings there send password-reset
links and "your password was changed" notices:

```bash
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=your-16-letter-app-password   # a Gmail App Password, not the account password
DEFAULT_FROM_EMAIL=FinTrack <you@gmail.com>
```

Without them, emails are printed to the console instead. Tests never send real mail.
