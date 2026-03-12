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