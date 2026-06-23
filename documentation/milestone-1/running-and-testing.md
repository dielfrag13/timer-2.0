# Milestone 1 — Running and Testing

This guide covers everything needed to set up, run, and manually verify the
Milestone 1 deliverables: Django project skeleton, environment-driven config,
PostgreSQL database, domain models, and structured JSON logging.

---

## Prerequisites

### Python

Python 3.10 or later is required. Verify with:

```bash
python3 --version
```

The virtual environment for this project lives at `backend/.venv` and is already
created. If you need to recreate it:

```bash
cd timer-2.0/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### PostgreSQL

A running PostgreSQL instance is required. On Ubuntu/WSL:

```bash
sudo apt install postgresql
sudo service postgresql start
```

Create the database user and database:

```bash
sudo -u postgres psql -c "CREATE USER timer WITH PASSWORD 'password';"
sudo -u postgres psql -c "CREATE DATABASE timer OWNER timer;"
```

---

## Environment Setup

Copy the example environment file and fill in the values:

```bash
cd timer-2.0/backend
cp .env.example .env
```

Open `.env` and set `SECRET_KEY` to the output of:

```bash
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

With the Postgres credentials above, your `.env` should look like:

```
SECRET_KEY=<generated value>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://timer:password@localhost:5432/timer
LOG_LEVEL=INFO
```

Set `DEBUG=True` for local development so the Django debug toolbar and detailed
error pages are active. The deployment check in the tests below is run with
`DEBUG=False` explicitly.

---

## Running the Development Server

```bash
cd timer-2.0/backend
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

The server will be available at `http://localhost:8000`.

---

## Manual Tests

Run these in order. Each test has a clear expected result.

---

### 1. Dependencies

Confirm all six required packages are installed at the correct versions:

```bash
.venv/bin/pip list | grep -E "Django|psycopg|whitenoise|gunicorn|environ|json-logger"
```

Expected output (versions may be newer within the pinned ranges):

```
django-environ    0.14.x
Django            5.2.x
gunicorn          26.x.x
psycopg           3.x.x
python-json-logger 4.x.x
whitenoise        6.x.x
```

---

### 2. System check

```bash
.venv/bin/python manage.py check
```

Expected:

```
System check identified no issues (0 silenced).
```

---

### 3. Migrations

Apply migrations and confirm the timer app's initial migration is marked complete:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py showmigrations timer
```

Expected output of `showmigrations`:

```
timer
 [X] 0001_initial
```

---

### 4. Django Admin — all five models present

Create a superuser if you haven't already:

```bash
.venv/bin/python manage.py createsuperuser
```

Start the server and visit `http://localhost:8000/admin/`. Log in with the
superuser credentials. Under the **Timer** section you should see:

- Operation instances
- Operation types
- Step instances
- Steps
- Surgeons

Try creating one of each to confirm the models accept data and save correctly.

---

### 5. Health endpoint

With the server running:

```bash
curl -s http://localhost:8000/health/
```

Expected:

```json
{"status": "ok"}
```

Also confirm the HTTP status code is 200:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health/
```

Expected: `200`

---

### 6. Deployment check

Run Django's built-in production readiness check. This must be run with
`DEBUG=False` to trigger all security checks:

```bash
DEBUG=False .venv/bin/python manage.py check --deploy
```

Expected:

```
System check identified no issues (2 silenced).
```

The 2 silenced items are:
- `security.W004` — HSTS headers (deferred to the K8s Ingress in Milestone 6)
- `security.W008` — `SECURE_SSL_REDIRECT` (TLS terminates at the Ingress, not in Django)

Any output other than this is a failure that must be investigated.

---

### 7. Structured JSON logging

Start the server with `LOG_LEVEL=DEBUG` and make any request:

```bash
LOG_LEVEL=DEBUG .venv/bin/python manage.py runserver
```

In a second terminal:

```bash
curl -s http://localhost:8000/health/
```

In the server terminal, every line of output should be valid JSON. A typical line
looks like:

```json
{"timestamp": "2026-06-23 18:33:13,557", "level": "INFO", "logger": "django.request", "message": "..."}
```

Confirm:
- All lines are parseable JSON (no plain-text lines)
- Each line contains `timestamp`, `level`, `logger`, and `message` keys
- Extra context fields (e.g. `request_id`) appear alongside the standard keys when present

---

### 8. Audit logger bypasses LOG_LEVEL

Verify that `timer.audit` always emits at INFO even when `LOG_LEVEL=WARNING`,
while other loggers are correctly silenced:

```bash
LOG_LEVEL=WARNING .venv/bin/python -c "
import django, logging, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'timer_server.settings'
django.setup()
logging.getLogger('timer.audit').info('audit always flows')
logging.getLogger('timer.api').info('this should be silent')
logging.getLogger('timer.auth').info('this should also be silent')
"
```

Expected: exactly one JSON line, from `timer.audit`. The `timer.api` and
`timer.auth` lines should not appear.

---

## Summary Checklist

| # | Test | Pass condition |
|---|---|---|
| 1 | Dependencies | All 6 packages listed at correct versions |
| 2 | `manage.py check` | 0 issues, 0 silenced |
| 3 | `manage.py migrate` | `[X] 0001_initial` shown |
| 4 | Django Admin | 5 models visible and writable |
| 5 | `curl /health/` | `{"status": "ok"}` with HTTP 200 |
| 6 | `check --deploy` | 0 issues, 2 silenced |
| 7 | JSON logging | Every log line is valid JSON with required keys |
| 8 | Audit logger | Only `timer.audit` emits when `LOG_LEVEL=WARNING` |
