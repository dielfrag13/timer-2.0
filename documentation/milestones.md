# Timer 2.0 — Milestone Plan

Timer 2.0 is a clean-slate rewrite of ASC Timer 1.0, redesigned as a Django REST API
backend + React SPA frontend backed by PostgreSQL, containerized for Docker and deployed
on Kubernetes. Timer 1.0 serves as a domain reference only — no schema, URL, or
installer compatibility is carried forward.

---

## Milestone 1 — Settings, Config & Logging Foundation

**Status:** Complete

Establishes the Django project skeleton with all configuration driven by environment
variables and a structured JSON logging baseline that every later milestone builds on.

Key outcomes:
- Django 5.2 project scaffolded under `backend/`
- All settings (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL`, `LOG_LEVEL`)
  read from environment via `django-environ`; no hardcoded values
- PostgreSQL only; SQLite removed
- `TIME_ZONE` corrected to `America/New_York`
- WhiteNoise middleware in correct position (second, after `SecurityMiddleware`)
- Domain models ported from 1.0 with clean-slate changes: `ocs1` flag replaced by
  `in_room_time` TimeField; `dist_from_average` CharField removed (will be a computed
  field in the serializer layer)
- All output to stdout in structured JSON (`timestamp`, `level`, `logger`, `message`)
- Logger hierarchy: `django`, `timer.api`, `timer.auth`, `timer.audit`; audit logger
  always emits at INFO regardless of `LOG_LEVEL`
- `GET /health/` endpoint for Docker and Kubernetes probes
- `manage.py check --deploy` passes with no warnings (2 intentionally silenced:
  HSTS and SSL redirect, both deferred to the K8s Ingress in M6)

---

## Milestone 2 — REST API Layer

**Status:** Complete

Replaces all server-rendered views with a Django REST Framework API. Django becomes
API-only (plus Django Admin).

Key outcomes:
- DRF installed; all five models exposed via ViewSets under `/api/v1/`
- `dist_from_average` computed as a read-only serializer field (per surgeon, per
  operation type, per step title — same scoping as 1.0, never written to the DB)
- OCS1 step-suggestion logic exposed as `GET /api/v1/operation-instances/{id}/suggested-steps/`
- Sequential time validation (each `end_time` ≥ previous) enforced in serializer
- `in_room_time` replaces the `ocs1`/`complete` two-step state machine
- CSV export at `GET /api/v1/operation-instances/{id}/export.csv/`
- Request/response middleware logs method, path, status, and duration via `timer.api`
- Slow query logging via `django.db.backends` at configurable threshold

---

## Milestone 3 — Authentication & Audit Logging

**Status:** Complete

Adds JWT-gated authentication and per-user data isolation. Establishes the audit trail.

Key outcomes:
- `djangorestframework-simplejwt`: login, token refresh, logout endpoints
- One-to-one `User → Surgeon` relationship; surgeons log in as themselves
- Admin role sees all data; standard users see only their own records
- Surgeon/user accounts created by admin only (no self-registration in 2.0)
- All non-health endpoints require `Authorization: Bearer <token>`
- `timer.audit` logger records login success/failure (with source IP), logout, and
  all `OperationInstance` create/update/delete events with user ID and timestamp

---

## Milestone 4 — Containerization

**Status:** Complete

Packages the full backend stack so it runs with a single `docker compose up`.

Key outcomes:
- `backend/Dockerfile`: Python 3.12 slim, installs requirements, runs `collectstatic`
  at build time
- `backend/entrypoint.sh`: waits for Postgres, runs `migrate`, starts Gunicorn
  with `--access-logfile -` and `--error-logfile -` (stdout only)
- `docker-compose.yml`: `postgres` service with named volume, `backend` service
  with `env_file: .env`
- `.dockerignore` excludes `__pycache__`, `.git`, `.venv`, `static_files/`
- `GET /health/` used as the Docker `HEALTHCHECK` target
- `docker compose logs` shows unified structured JSON stream for all services

---

## Milestone 5 — Frontend App

**Status:** Planned

Builds a React SPA that fully replaces the Django template UI from 1.0.

Key outcomes:
- React + Vite, React Router, Axios + React Query, Bootstrap
- Pages: Login, Dashboard, Surgeons, Operations, Begin Operation, OCS1 (step list),
  OCS2 (timing with In-room / Now buttons), Post-op stats
- JWT tokens stored in `httpOnly` cookies
- `dist_from_average` rendered with color coding
- Multi-stage `frontend/Dockerfile`: Node build stage → nginx serve stage
- `nginx.conf` proxies `/api/` and `/admin/` to backend; SPA fallback for all other paths
- Added as `frontend` service in `docker-compose.yml`

---

## Milestone 6 — Kubernetes & Log Aggregation

**Status:** Planned

Deploys the full stack to Kubernetes and wires up log aggregation.

Key outcomes:
- Namespace `timer`; separate Deployments for backend and frontend
- ConfigMap for non-sensitive config; Secret for `SECRET_KEY`, `DATABASE_URL`
- Postgres StatefulSet + PVC (with a note to substitute a managed DB in production)
- Pre-deploy migration Job runs `manage.py migrate` before the backend Deployment rolls out
- Ingress with HTTPS via `cert-manager` + Let's Encrypt
- HorizontalPodAutoscaler: backend scales 2–6 replicas on CPU
- Loki + Grafana for log aggregation; manifests in `k8s/logging/`
- Pre-built Grafana dashboards for the `timer.audit` stream and the `timer.api`
  request/error rate stream
- `LOG_LEVEL` in ConfigMap is the single dial to change verbosity without redeployment
