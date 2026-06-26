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

**Status:** Complete

Builds a React SPA that fully replaces the Django template UI from 1.0.

Key outcomes:
- React 18 + Vite 8; React Router v6 nested routes; `@tanstack/react-query`;
  Axios with httpOnly cookie auth; Bootstrap 5 (CSS only, no Bootstrap JS)
- JWT stored in `httpOnly; SameSite=Lax` cookies (`timer_access`,
  `timer_refresh`); `CookieJWTAuthentication` backend class falls through to
  cookie after checking the `Authorization` header
- `GET /api/v1/auth/me/` endpoint for session bootstrap; `AuthContext` holds
  `user` (null when logged out) and guards all authenticated routes via
  `PrivateRoute` (`<Outlet />` pattern)
- Axios 401 interceptor silently refreshes the access token then retries the
  original request; hard-redirects to `/login` if refresh fails
- Pages: Login, Dashboard, Surgeons, Operation Types, Begin Operation, OCS1
  (step setup), OCS2 (live timing with running clock + per-step Now buttons),
  Post-op Stats (color-coded `dist_from_average` table + CSV download)
- Multi-stage `frontend/Dockerfile`: node:20-alpine build stage → nginx:alpine
  serve stage; `npm ci` layer is cached unless `package*.json` changes
- `frontend/nginx.conf`: proxies `/api/` and `/admin/` to
  `http://backend:8000`; `try_files` SPA fallback for all other paths
- `frontend` service added to `docker-compose.yml` on port 80; backend port
  8000 removed from host mapping (all traffic through nginx)

---

## Milestone 6 — Kubernetes & Log Aggregation

**Status:** Complete

Deploys the full stack to Kubernetes using kind for local development and
documents the path to a real cloud cluster. Adds Loki + Promtail + Grafana
for log aggregation with pre-built dashboards.

Key outcomes:
- `k8s/namespace.yaml` — all application resources isolated in the `timer` namespace
- `k8s/configmap.yaml` — non-sensitive env vars (`DEBUG`, `LOG_LEVEL`,
  `ALLOWED_HOSTS`); `k8s/secret.yaml` (gitignored) holds `SECRET_KEY`,
  `DATABASE_URL`, and Postgres credentials; `secret.example.yaml` is the
  checked-in template
- `backend/timer_server/settings.py` — `SECURE_PROXY_SSL_HEADER` added so
  Django correctly identifies HTTPS requests forwarded by nginx-ingress
- `k8s/postgres/` — StatefulSet (1 replica, `postgres:16-alpine`); `PGDATA`
  set to a subdirectory to avoid the `lost+found` mount issue; `pg_isready`
  readiness + liveness probes; 10 Gi `volumeClaimTemplates` PVC; ClusterIP
  Service named `postgres`
- `k8s/backend/migration-job.yaml` — Job that reuses `entrypoint.sh` by
  overriding CMD to `true`; `backoffLimit: 3`; `ttlSecondsAfterFinished: 300`
- `k8s/backend/deployment.yaml` — 2 replicas; `imagePullPolicy: Never`;
  `envFrom` ConfigMap + Secret; readiness probe (15s delay) + liveness probe
  (60s delay) on `GET /health/`
- `k8s/backend/service.yaml` — ClusterIP named `backend` on port 8000 (matches
  `nginx.conf` proxy_pass — same name as Docker Compose)
- `k8s/backend/hpa.yaml` — `autoscaling/v2`; 2–6 replicas at 70% average CPU;
  requires metrics-server
- `k8s/frontend/` — 1 replica nginx Deployment; no env injection (config baked
  at build time); same image as M5 unchanged; ClusterIP Service named `frontend`
- `k8s/ingress/clusterissuer-selfsigned.yaml` — self-signed issuer for kind
- `k8s/ingress/clusterissuer-letsencrypt.yaml` — Let's Encrypt ACME HTTP-01
  for production; email `kyle.buchmiller@gmail.com`
- `k8s/ingress/ingress.yaml` — `ingressClassName: nginx`; all traffic routes to
  frontend Service (nginx handles internal `/api/` proxying); TLS via
  cert-manager annotation; host `timer.local` for kind
- `k8s/logging/loki-values.yaml` — single-binary Loki, filesystem storage,
  TSDB schema v13, auth disabled, 10 Gi PVC
- `k8s/logging/promtail-values.yaml` — DaemonSet; 3-stage pipeline: `cri: {}`
  → `json` (extracts `level`, `logger`) → `labels`; non-JSON lines stored without labels
- `k8s/logging/grafana-values.yaml` — Loki datasource provisioned; sidecar
  watches `grafana_dashboard=1` ConfigMaps; access via port-forward port 3000
- `k8s/logging/dashboards/audit.json` — stats (total events, login failures,
  operations completed); activity time series; raw audit log panel
- `k8s/logging/dashboards/api-requests.json` — stats (total, 5xx, 4xx);
  request rate + avg/p95 response time via `unwrap duration_ms`; error log panel
- `k8s/kind-config.yaml` — single control-plane node; `ingress-ready=true`
  node label; port mappings 80→80, 443→443
- `k8s/scripts/setup-kind.sh` — creates cluster; installs ingress-nginx,
  cert-manager, metrics-server, Loki, Promtail, Grafana; idempotent
- `k8s/scripts/build-images.sh` — builds and kind-loads `timer-backend:latest`
  and `timer-frontend:latest`
- `k8s/scripts/apply.sh` — applies all manifests in dependency order with
  `kubectl wait` gates; delete+recreate migration Job on each run
- `documentation/dependencies.md` — complete install reference for all system
  tools, Python packages, npm packages, and Helm charts across all milestones
- `documentation/troubleshooting.md` — running log of problems and fixes
- `documentation/milestone-6/` — design-decisions.md, implementation-steps.md,
  implementation-notes.md, grafana-guide.md, running-and-testing.md
