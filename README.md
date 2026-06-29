# Timer 2.0

A production-quality surgical procedure timing application for ambulatory surgery centers. Timer 2.0 is a clean-slate rewrite of ASC Timer 1.0, rebuilt as a Django REST API backend and React SPA frontend, containerized with Docker, and deployable to Kubernetes.

---

## What it does

Operating room nurses use Timer 2.0 to time each step of a surgical procedure in real time. After the procedure, the system compares step durations against historical averages for that surgeon and procedure type, surfacing deviations as color-coded statistics that help identify inefficiencies and track improvement over time.

**Workflow:**
1. Admin creates surgeons, operation types, and reusable step definitions
2. Nurse begins an operation — selects surgeon, operation type, and date
3. OCS1 (Operation Control Screen 1) — nurse builds the step list, optionally using steps suggested from prior history, then marks the patient as "in room"
4. OCS2 (Operation Control Screen 2) — nurse records start and end times for each step using "Now" buttons while a running clock tracks total time in room
5. Post-op Stats — completed operation shows a table of each step's duration vs. historical average, color-coded by deviation; downloadable as CSV

---

## Architecture

```
Browser
  └── HTTPS → nginx-ingress (TLS termination)
                └── frontend nginx (port 80)
                      ├── static files  →  React SPA (pre-built, served directly)
                      └── /api/, /admin/ →  backend Service (port 8000)
                                              └── Django + Gunicorn (2–6 pods, HPA)
                                                    └── PostgreSQL (StatefulSet)
```

**Observability:**
```
All pods → stdout (JSON)
  └── Promtail (DaemonSet) → Loki → Grafana dashboards
```

---

## Technology stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2, Django REST Framework, SimpleJWT |
| Frontend | React 19, React Router 7, TanStack Query, Axios, Bootstrap 5 |
| Database | PostgreSQL 16 |
| Auth | JWT in httpOnly cookies; `CookieJWTAuthentication` backend class |
| Container runtime | Docker + Docker Compose (local dev) |
| Orchestration | Kubernetes via kind (local), any cloud K8s (production) |
| Ingress / TLS | nginx-ingress + cert-manager (self-signed or Let's Encrypt) |
| Autoscaling | HorizontalPodAutoscaler, 2–6 backend replicas at 70% CPU |
| Log aggregation | Promtail → Loki → Grafana |
| Build tooling | Vite 8, multi-stage Docker builds |

---

## Repository layout

```
timer-2.0/
├── backend/                  Django project
│   ├── timer/                Application code (models, views, serializers, services)
│   ├── timer_server/         Project settings, URLs, WSGI
│   ├── Dockerfile
│   ├── entrypoint.sh         Waits for Postgres, runs migrations, starts Gunicorn
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/                 React SPA
│   ├── src/
│   │   ├── pages/            Login, Dashboard, Surgeons, OperationTypes,
│   │   │                     BeginOperation, OCS1, OCS2, PostOpStats
│   │   ├── api/client.js     Axios instance with 401→refresh interceptor
│   │   ├── context/          AuthContext (user session state)
│   │   └── components/       Layout, Modal, PrivateRoute
│   ├── nginx.conf            Proxies /api/ and /admin/ to backend; SPA fallback
│   └── Dockerfile            node:20-alpine build → nginx:alpine serve
├── k8s/                      Kubernetes manifests
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.example.yaml   Template — copy to secret.yaml and fill in values
│   ├── postgres/             StatefulSet + Service
│   ├── backend/              Deployment, Service, HPA, migration Job
│   ├── frontend/             Deployment, Service
│   ├── ingress/              ClusterIssuers (self-signed, Let's Encrypt), Ingress
│   ├── logging/              Loki, Promtail, Grafana Helm values + dashboard JSON
│   ├── kind-config.yaml      Local cluster definition
│   └── scripts/              setup-kind.sh, build-images.sh, apply.sh
├── docker-compose.yml
└── documentation/
    ├── milestones.md         Full milestone history and outcomes
    ├── dependencies.md       All system tools, packages, and Helm charts
    ├── troubleshooting.md    Problems encountered and how they were resolved
    └── milestone-{1..6}/     Per-milestone design decisions, implementation
                               notes, and running/testing guides
```

---

## Domain model

| Model | Description |
|---|---|
| `Surgeon` | Person performing operations (name, email, linked Django user) |
| `OperationType` | Reusable procedure category (e.g., "Total Knee Replacement") |
| `Step` | Named, globally reusable procedure milestone (e.g., "Incision") |
| `OperationInstance` | One performed procedure — links surgeon, type, date; tracks `in_room_time`, `complete`, `elapsed_time` |
| `StepInstance` | Records `start_time`, `end_time`, `elapsed_time`, and `dist_from_average` for one step within one operation |

`dist_from_average` is computed at query time per surgeon, operation type, and step title — it is never stored in the database.

Audit events are emitted to stdout as structured JSON via the `timer.audit` logger and collected by Loki. They are not stored in the database.

---

## Running locally

### Option A — Docker Compose (simplest)

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set DATABASE_URL=postgres://timer:password@db:5432/timer

docker compose up --build
```

Access at `http://localhost`. Create a superuser:

```bash
docker compose exec backend python manage.py createsuperuser
```

### Option B — Local development servers (faster iteration)

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
# Edit .env — set DATABASE_URL=postgres://timer:password@localhost:5432/timer
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver

# Frontend (separate terminal)
cd frontend
source ~/.nvm/nvm.sh && npm install
source ~/.nvm/nvm.sh && npm run dev
```

Access at `http://localhost:5173`. Vite proxies `/api/` and `/admin/` to Django on port 8000.

### Running tests

```bash
cd backend
DATABASE_URL=postgres://timer:password@localhost:5432/timer .venv/bin/pytest
```

---

## Running on Kubernetes (kind)

Full instructions in `documentation/milestone-6/running-and-testing.md`. The short version:

```bash
# 1. Stop Docker Compose if running (kind needs ports 80 and 443)
docker compose down

# 2. Create cluster and install tooling — ingress-nginx, cert-manager,
#    metrics-server, Loki, Promtail, Grafana (~5 minutes first run)
k8s/scripts/setup-kind.sh

# 3. Build application images and load into the cluster
k8s/scripts/build-images.sh

# 4. Create your secret file
cp k8s/secret.example.yaml k8s/secret.yaml
# Edit k8s/secret.yaml — set SECRET_KEY, DATABASE_URL, and Postgres credentials

# 5. Deploy
k8s/scripts/apply.sh
```

Add `timer.local` to your hosts file — on Linux/WSL2:
```bash
echo "127.0.0.1 timer.local" | sudo tee -a /etc/hosts
```
On Windows (hosts file at `C:\Windows\System32\drivers\etc\hosts`, edit as Administrator):
```
127.0.0.1 timer.local
```

Open `https://timer.local` (accept the self-signed certificate warning on first load).

**Grafana:**
```bash
kubectl port-forward svc/grafana 3000:80 -n logging
# Open http://localhost:3000  —  admin / admin
```

---

## API overview

All endpoints require JWT authentication via httpOnly cookie (set by `/api/v1/auth/login/`).

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login/` | Obtain access + refresh tokens (set as cookies) |
| `POST` | `/api/v1/auth/refresh/` | Refresh access token |
| `POST` | `/api/v1/auth/logout/` | Blacklist refresh token, clear cookies |
| `GET` | `/api/v1/auth/me/` | Current user info including `surgeon_id` |
| `GET/POST` | `/api/v1/surgeons/` | List / create surgeons (admin only) |
| `GET/POST` | `/api/v1/operation-types/` | List / create operation types |
| `GET/POST` | `/api/v1/steps/` | List / create steps |
| `GET/POST` | `/api/v1/operation-instances/` | List / create operation instances |
| `GET/PATCH` | `/api/v1/operation-instances/{id}/` | Detail / update (complete, in_room_time) |
| `GET` | `/api/v1/operation-instances/{id}/suggested-steps/` | Steps ordered by historical frequency |
| `GET` | `/api/v1/operation-instances/{id}/export-csv/` | Download step timing as CSV |
| `GET/POST` | `/api/v1/step-instances/` | List / create step instances |
| `GET/PATCH` | `/api/v1/step-instances/{id}/` | Detail / update (start_time, end_time) |
| `GET` | `/health/` | Health check (used by Docker and Kubernetes probes) |

---

## Configuration

All configuration is driven by environment variables. See `documentation/dependencies.md` for the full reference.

| Variable | Where set | Description |
|---|---|---|
| `SECRET_KEY` | `.env` / K8s Secret | Django secret key |
| `DATABASE_URL` | `.env` / K8s Secret | Postgres connection string |
| `DEBUG` | `.env` / K8s ConfigMap | `True` for local dev, `False` in production |
| `ALLOWED_HOSTS` | `.env` / K8s ConfigMap | Comma-separated hostnames Django will serve |
| `LOG_LEVEL` | `.env` / K8s ConfigMap | `DEBUG`, `INFO`, or `WARNING` — controls all loggers except `timer.audit` (always INFO) |

`k8s/secret.yaml` is gitignored and must never be committed. Use `k8s/secret.example.yaml` as the template.

---

## Documentation

| File | Contents |
|---|---|
| `documentation/milestones.md` | Full milestone history with outcomes for each |
| `documentation/dependencies.md` | Every system tool, Python package, npm package, and Helm chart with install commands |
| `documentation/troubleshooting.md` | Problems encountered during development and their fixes |
| `documentation/milestone-6/design-decisions.md` | Verbose explanation of every Kubernetes technology used and why |
| `documentation/milestone-6/grafana-guide.md` | How to use the Grafana dashboards, LogQL query cookbook |
| `documentation/milestone-6/running-and-testing.md` | Full K8s setup walkthrough, manual test checklist, cloud migration guide |
