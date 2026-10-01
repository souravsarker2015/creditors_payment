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

Switch by setting `DJANGO_SETTINGS_MODULE`:

```bash
export DJANGO_SETTINGS_MODULE=config.settings.prod
```