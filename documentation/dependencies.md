# Timer 2.0 — Dependencies and Installation Reference

This document is a single source of truth for every tool, package, and library
that timer-2.0 depends on. It covers what the dependency is, which milestone
introduced it, what command installs it, and what version was used during
development. Commands are written for Ubuntu/Debian (WSL2 Ubuntu 22.04).

---

## Table of contents

1. [System tools](#1-system-tools)
2. [Python runtime and virtual environment](#2-python-runtime-and-virtual-environment)
3. [Python packages — backend](#3-python-packages--backend)
4. [PostgreSQL — local development](#4-postgresql--local-development)
5. [Docker Engine and Docker Compose](#5-docker-engine-and-docker-compose)
6. [Node.js — via nvm](#6-nodejs--via-nvm)
7. [npm packages — frontend](#7-npm-packages--frontend)
8. [Kubernetes tooling](#8-kubernetes-tooling)
9. [Helm charts — third-party K8s tools](#9-helm-charts--third-party-k8s-tools)
10. [Versions at a glance](#10-versions-at-a-glance)

---

## 1. System tools

These are apt packages installed on the host machine (or inside Docker
containers). They are prerequisites for the development workflow, not
application runtime dependencies.

### `build-essential`, `libpq-dev` — C compiler + Postgres headers

**Milestone:** M1  
**Why:** `psycopg` (the Python Postgres driver) compiles a C extension during
`pip install`. Without a C compiler and the Postgres client headers, pip fails
with an error about missing `pg_config`.

```bash
sudo apt-get update
sudo apt-get install -y build-essential libpq-dev
```

### `python3-venv` — virtual environment support

**Milestone:** M1  
**Why:** Ubuntu's system Python does not include `venv` by default. Without
this package, `python3 -m venv .venv` fails.

```bash
sudo apt-get install -y python3-venv
```

### `postgresql-client` — `pg_isready` CLI

**Milestone:** M4 (used inside the backend Docker container)  
**Why:** `backend/entrypoint.sh` calls `pg_isready` in a loop to wait for
Postgres to accept connections before running migrations. `pg_isready` ships
with `postgresql-client`, not the server.  
**Where installed:** Inside the backend Docker image (see `backend/Dockerfile`).
Not required on the host machine.

```bash
# Inside the Docker image — this runs during `docker build`
apt-get install -y --no-install-recommends postgresql-client
```

### `curl` — HTTP probe

**Milestone:** M4 (used inside the backend Docker container)  
**Why:** `docker-compose.yml` uses `curl -f http://localhost:8000/health/` as
the Docker health check command to determine when the backend is ready.  
**Where installed:** Inside the backend Docker image.

```bash
# Inside the Docker image
apt-get install -y --no-install-recommends curl
```

---

## 2. Python runtime and virtual environment

### Python 3.10 (system) / Python 3.12 (Docker)

**Milestone:** M1  
**Why:** Django 5.2 requires Python 3.10 or later. The host machine uses the
system Python 3.10 (Ubuntu 22.04 default). The backend Docker image uses
Python 3.12 (the `python:3.12-slim` base image) for a more recent runtime in
production.

```bash
# Check what's installed
python3 --version
# → Python 3.10.12 (on this machine)

# Ubuntu 22.04 ships Python 3.10 — no additional install needed.
# If Python 3.10+ is missing, install via deadsnakes PPA:
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev
```

### Virtual environment

**Milestone:** M1  
**Why:** Isolates Python packages so project dependencies don't conflict with
system packages or other Python projects.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # or use .venv/bin/python / .venv/bin/pip directly
```

`.venv/` is listed in `.gitignore` and is never committed.

### pip

**Milestone:** M1  
**Why:** Installs Python packages from `requirements.txt`.

```bash
# Upgrade pip inside the venv first
.venv/bin/pip install --upgrade pip

# Install all backend dependencies
.venv/bin/pip install -r requirements.txt

# Install dev-only dependencies (pytest etc.)
.venv/bin/pip install -r requirements-dev.txt
```

---

## 3. Python packages — backend

All packages listed in `backend/requirements.txt` and `backend/requirements-dev.txt`.

### Django `>=5.2,<6.0`

**Milestone:** M1  
**Why:** The web framework. Handles URL routing, ORM, admin interface,
management commands (`migrate`, `createsuperuser`), and the settings system.
Version 5.2 is the current LTS release.

```bash
.venv/bin/pip install "Django>=5.2,<6.0"
# or via requirements.txt
```

### `psycopg[binary] >=3.2`

**Milestone:** M1  
**Why:** The PostgreSQL database adapter for Python. The `[binary]` extra
installs a pre-compiled wheel instead of compiling from source — faster and
avoids the `libpq-dev` system dependency on the host (the binary wheel bundles
the Postgres client library). `psycopg` v3 is the modern rewrite of `psycopg2`
with async support and a cleaner API.

```bash
.venv/bin/pip install "psycopg[binary]>=3.2"
```

### `django-environ >=0.11`

**Milestone:** M1  
**Why:** Reads configuration values (SECRET_KEY, DATABASE_URL, DEBUG, etc.)
from environment variables and `.env` files. The `env()` call in `settings.py`
replaces all hardcoded values. `DATABASE_URL=postgres://user:pass@host/db` is
parsed into the `DATABASES` dict automatically.

```bash
.venv/bin/pip install "django-environ>=0.11"
```

### `gunicorn >=23.0`

**Milestone:** M1 (configured), M4 (used in production)  
**Why:** The WSGI server that runs Django in production. Django's built-in
`runserver` is single-threaded and not suitable for production. Gunicorn
spawns multiple worker processes to handle concurrent requests. The backend
Docker image uses Gunicorn as its CMD; `manage.py runserver` is used for local
development only.

```bash
.venv/bin/pip install "gunicorn>=23.0"
```

### `whitenoise >=6.9`

**Milestone:** M1  
**Why:** Serves Django's static files (admin CSS/JS) directly from the Python
process without needing a separate nginx or CDN. In Docker, the backend runs
behind nginx (via the frontend container) which could handle static files, but
WhiteNoise keeps the backend self-contained. Configured as Django middleware.

```bash
.venv/bin/pip install "whitenoise>=6.9"
```

### `python-json-logger >=3.0`

**Milestone:** M1  
**Why:** Formats Python log records as JSON objects instead of plain text lines.
Combined with Django's `LOGGING` config in `settings.py`, every log line from
the backend is a single JSON object with `timestamp`, `level`, `logger`, and
`message` fields. Promtail (M6) can parse these fields as labels for filtering
in Grafana.

```bash
.venv/bin/pip install "python-json-logger>=3.0"
```

### `djangorestframework >=3.15`

**Milestone:** M2  
**Why:** Adds the REST framework layer to Django: serializers (convert model
instances to/from JSON), ViewSets (CRUD views with one class), Routers
(auto-generate URLs from ViewSets), and authentication/permission classes.

```bash
.venv/bin/pip install "djangorestframework>=3.15"
```

### `django-filter >=24.0`

**Milestone:** M2  
**Why:** Adds query-parameter filtering to DRF ViewSets. Used to filter
`OperationInstance` by `complete=true/false` (Dashboard active vs completed
lists) and `StepInstance` by `operation_instance` (OCS1 and OCS2 step lists).
Without it, the frontend would have to fetch all records and filter client-side.

```bash
.venv/bin/pip install "django-filter>=24.0"
```

### `djangorestframework-simplejwt >=5.3`

**Milestone:** M3  
**Why:** Implements JSON Web Token (JWT) authentication for DRF. Provides login
(`TokenObtainPairView`), token refresh (`TokenRefreshView`), and token blacklist
(logout) endpoints out of the box. Timer-2.0 extends these views to set tokens
in httpOnly cookies rather than returning them in the response body.

```bash
.venv/bin/pip install "djangorestframework-simplejwt>=5.3"
```

### `pytest >=8.0` (dev only)

**Milestone:** M2  
**Why:** Test runner. More ergonomic than Django's built-in `unittest` runner:
fixtures are injected via function arguments, no class boilerplate required,
better failure output.

```bash
.venv/bin/pip install "pytest>=8.0"
```

### `pytest-django >=4.8` (dev only)

**Milestone:** M2  
**Why:** Integrates pytest with Django: provides the `db` fixture (database
access in tests), `client` and `api_client` fixtures, `settings` override, and
`--ds` flag to point pytest at the Django settings module. Without this, pytest
doesn't know how to set up or tear down the Django test database.

```bash
.venv/bin/pip install "pytest-django>=4.8"
```

**Installing all at once:**
```bash
cd backend
.venv/bin/pip install -r requirements.txt      # production deps
.venv/bin/pip install -r requirements-dev.txt  # + pytest
```

---

## 4. PostgreSQL — local development

**Milestone:** M1  
**Why:** The application requires PostgreSQL. SQLite is explicitly not supported
(removed from DATABASES config). For local development, Postgres runs on the
host machine. For Docker Compose, it runs as the `db` container.

### Installing PostgreSQL on Ubuntu 22.04

```bash
sudo apt-get install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### Creating the development database

```bash
sudo -u postgres psql -c "CREATE USER timer WITH PASSWORD 'password';"
sudo -u postgres psql -c "CREATE DATABASE timer OWNER timer;"
```

### `backend/.env` — database connection string

The `DATABASE_URL` environment variable switches depending on how you're
running the app. The format is always:
```
DATABASE_URL=postgres://<user>:<password>@<host>:<port>/<dbname>
```

| Context | Value |
|---|---|
| Local dev / pytest | `DATABASE_URL=postgres://timer:password@localhost:5432/timer` |
| Docker Compose | `DATABASE_URL=postgres://timer:password@db:5432/timer` |
| Kubernetes | `DATABASE_URL=postgres://timer:password@postgres:5432/timer` |

The hostname changes to match the service name in each environment.

---

## 5. Docker Engine and Docker Compose

**Milestone:** M4

### Docker Engine

**Why:** Runs containerized services (`db`, `backend`, `frontend`). Required for
Docker Compose and for kind (which creates Kubernetes nodes as Docker
containers).

```bash
# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the Docker apt repository (single unbroken line)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# Allow running Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

Version in use: `29.1.3`

### Docker Compose plugin (`docker compose`)

**Why:** Runs the multi-container application stack from `docker-compose.yml`
with a single command (`docker compose up --build`). The Compose v2 plugin
(`docker compose` with a space) replaced the legacy `docker-compose` standalone
binary. Note: this was a pain point during M4 — the plugin is not installed
automatically with Docker Engine on Ubuntu; it requires the step below.

```bash
sudo apt-get install -y docker-compose-plugin
```

Version in use: `v5.2.0`

**Verify:**
```bash
docker --version
docker compose version
```

---

## 6. Node.js — via nvm

**Milestone:** M5

### nvm (Node Version Manager)

**Why:** Node.js has frequent major releases and projects often require a
specific version. nvm lets you install and switch between Node.js versions
without root access or conflicts with system packages. This is the recommended
way to install Node.js for development.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

After installing, either open a new terminal or source the nvm script:
```bash
source ~/.nvm/nvm.sh
```

**Non-interactive shell note:** Claude's shell is non-interactive and does not
source `~/.bashrc` or `~/.nvm/nvm.sh` automatically. All `node` and `npm`
commands run by Claude are prefixed with `source ~/.nvm/nvm.sh &&`. When you
run these commands yourself in an interactive terminal where you've already
loaded nvm, the prefix is not needed.

### Node.js 20 (LTS)

**Why:** Node 20 is the current LTS (Long-Term Support) release. Vite 8 and
all frontend dependencies support it. The frontend Docker image uses
`node:20-alpine` for the same reason.

```bash
source ~/.nvm/nvm.sh
nvm install 20
nvm alias default 20
```

Version in use: `v20.20.2` (Node), `10.8.2` (npm)

**Verify:**
```bash
source ~/.nvm/nvm.sh
node --version
npm --version
```

---

## 7. npm packages — frontend

All packages listed in `frontend/package.json`. Install with:

```bash
cd frontend
source ~/.nvm/nvm.sh && npm install
```

### React `^19.2.7` + `react-dom`

**Milestone:** M5  
**Why:** The UI framework. React lets you build the interface as a tree of
components (reusable JavaScript functions that return HTML). `react-dom` is the
package that actually renders React components to the browser's DOM. Both are
always installed together.

### `react-router-dom ^7.18.0`

**Milestone:** M5  
**Why:** Client-side routing for the SPA. Lets React handle navigation between
pages (`/`, `/surgeons`, `/operations/:id/ocs2`) without a full page reload.
Uses the browser's History API so URLs look normal. The `<BrowserRouter>`,
`<Routes>`, `<Route>`, `<Link>`, `useParams`, `useNavigate` primitives all
come from this package.

### `@tanstack/react-query ^5.101.1`

**Milestone:** M5  
**Why:** Server state management — fetching, caching, and invalidating API data.
Without React Query, every component that needs API data would have to manage
its own loading/error state and figure out when to refetch. React Query caches
responses by query key (`['surgeons']`, `['operation-instance', id]`), deduplicates
concurrent requests, and updates the UI automatically when a mutation invalidates
a cache entry.

### `axios ^1.18.1`

**Milestone:** M5  
**Why:** HTTP client for API requests. Used instead of the browser's built-in
`fetch` because: (1) `withCredentials: true` can be set once on a shared
instance rather than on every request; (2) response interceptors let the 401
auto-refresh logic live in one place (`src/api/client.js`) rather than being
duplicated across every component.

### `bootstrap ^5.3.8`

**Milestone:** M5  
**Why:** CSS framework providing a grid system, utility classes, and pre-styled
components (tables, buttons, modals, alerts, badges). Only the CSS is used —
Bootstrap's JavaScript (for modal animations etc.) is deliberately excluded
because React manages all state and DOM updates. Bootstrap JS fights with React
for control of the DOM.

```bash
# All frontend packages installed together:
cd frontend
source ~/.nvm/nvm.sh && npm install
```

### Dev dependencies

| Package | Purpose |
|---|---|
| `vite ^8.1.0` | Build tool and dev server; bundles the React app for production and serves it with HMR (Hot Module Replacement) during development |
| `@vitejs/plugin-react ^6.0.2` | Vite plugin that adds React JSX transformation and Fast Refresh (component-level hot reload without losing state) |
| `oxlint ^1.69.0` | JavaScript linter; faster than ESLint; catches common mistakes |
| `@types/react` + `@types/react-dom` | TypeScript type definitions for React (used by editor autocomplete even in a non-TypeScript project) |

---

## 8. Kubernetes tooling

**Milestone:** M6

### `kubectl`

**Why:** The Kubernetes command-line tool. Every Kubernetes operation — applying
manifests, checking pod status, reading logs, executing a shell inside a pod —
goes through `kubectl`. It communicates with the cluster's API server over HTTPS
using credentials stored in `~/.kube/config`.

```bash
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg

curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key \
  | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' \
  | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update && sudo apt-get install -y kubectl
```

### `kind` (Kubernetes IN Docker)

**Why:** Creates a local Kubernetes cluster entirely inside Docker containers.
Used in Milestone 6 to test all Kubernetes manifests without a cloud account.
The same manifests work unchanged on GKE, EKS, or AKS — kind is only a local
development tool, not a production runtime.

```bash
curl -Lo /tmp/kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64
chmod +x /tmp/kind
sudo mv /tmp/kind /usr/local/bin/kind
```

### `helm`

**Why:** Package manager for Kubernetes. Third-party tools (ingress-nginx,
cert-manager, Loki, Promtail, Grafana) each require dozens of Kubernetes
resources to be created in the right order with the right configuration. Helm
bundles all of that into a single installable *chart*. We write custom YAML
only for timer-2.0's own resources; everything else comes from official Helm
charts.

```bash
HELM_BUILDKITE_APT_KEY_ID="DDF78C3E6EBB2D2CC223C95C62BA89D07698DBC6"

sudo apt-get install -y curl gpg apt-transport-https

curl -fsSL https://packages.buildkite.com/helm-linux/helm-debian/gpgkey > "${TMPDIR:-/tmp}/helm.gpg"

# Verify the key fingerprint to guard against repository compromise
if [ "$(gpg --show-keys --with-colons "${TMPDIR:-/tmp}/helm.gpg" | awk -F: '$1 == "fpr" {print $10}' | head -n 1)" != "${HELM_BUILDKITE_APT_KEY_ID}" ]; then
  echo "ERROR: Unexpected Helm APT key ID: potential key compromise"
  exit 1
fi

cat "${TMPDIR:-/tmp}/helm.gpg" | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null

echo "deb [signed-by=/usr/share/keyrings/helm.gpg] https://packages.buildkite.com/helm-linux/helm-debian/any/ any main" \
  | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list

sudo apt-get update && sudo apt-get install -y helm
```

**Verify all three:**
```bash
kubectl version --client
kind version
helm version
```

---

## 9. Helm charts — third-party K8s tools

These are installed into the cluster via `helm install`, not via `apt`. All
installation commands are in `k8s/scripts/setup-kind.sh` and the M6
running-and-testing guide. Listed here for reference.

### `ingress-nginx` (Helm chart: `ingress-nginx/ingress-nginx`)

**Milestone:** M6  
**Why:** The Ingress controller — the pod that actually handles incoming HTTP/HTTPS
traffic and routes it based on the Ingress rules defined in
`k8s/ingress/ingress.yaml`. Without a controller, Ingress resources are inert
YAML that do nothing.

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.hostPort.enabled=true
```

### `cert-manager` (Helm chart: `cert-manager/cert-manager`)

**Milestone:** M6  
**Why:** Automates TLS certificate issuance and renewal. Watches Ingress resources
for the `cert-manager.io/cluster-issuer` annotation and requests certificates
from the configured CA (self-signed for local kind, Let's Encrypt for
production). Stores the cert as a Kubernetes Secret and keeps it renewed.

```bash
helm repo add cert-manager https://charts.jetstack.io
helm install cert-manager cert-manager/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
```

### `loki` (Helm chart: `grafana/loki`)

**Milestone:** M6  
**Why:** Log aggregation backend. Receives structured JSON logs from Promtail,
stores them in compressed chunks, and exposes a query API (LogQL) that Grafana
uses for dashboards. Chosen over Elasticsearch for its dramatically lower
resource requirements.

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki \
  --namespace logging --create-namespace \
  --values k8s/logging/loki-values.yaml
```

### `promtail` (Helm chart: `grafana/promtail`)

**Milestone:** M6  
**Why:** Log collection agent. Runs as a DaemonSet (one pod per cluster node),
reads all pod stdout/stderr from `/var/log/pods/` on the node's filesystem,
parses the JSON fields that Django emits (`level`, `logger`, `message`), attaches
Kubernetes metadata (pod name, namespace, app label), and ships log entries to
Loki.

```bash
helm install promtail grafana/promtail \
  --namespace logging \
  --values k8s/logging/promtail-values.yaml
```

### `grafana` (Helm chart: `grafana/grafana`)

**Milestone:** M6  
**Why:** Visualization UI. Connects to Loki as a datasource and renders
LogQL query results as dashboards. The two pre-built dashboards (audit events
and API request metrics) are provisioned automatically via a ConfigMap mounted
into the Grafana pod — no manual clicking required after installation.

```bash
helm install grafana grafana/grafana \
  --namespace logging \
  --values k8s/logging/grafana-values.yaml
```

---

## 10. Versions at a glance

| Tool / Package | Version | Where used | Milestone |
|---|---|---|---|
| Python | 3.10.12 (host), 3.12 (Docker) | Backend runtime | M1 |
| Django | ≥5.2,<6.0 | Web framework | M1 |
| psycopg[binary] | ≥3.2 | Postgres driver | M1 |
| django-environ | ≥0.11 | Config from env vars | M1 |
| gunicorn | ≥23.0 | Production WSGI server | M1/M4 |
| whitenoise | ≥6.9 | Serves Django static files | M1 |
| python-json-logger | ≥3.0 | Structured JSON logging | M1 |
| djangorestframework | ≥3.15 | REST API layer | M2 |
| django-filter | ≥24.0 | Query-param filtering | M2 |
| djangorestframework-simplejwt | ≥5.3 | JWT authentication | M3 |
| pytest | ≥8.0 | Test runner (dev) | M2 |
| pytest-django | ≥4.8 | Django test integration (dev) | M2 |
| PostgreSQL | 16 (Docker), 14+ (local) | Database | M1 |
| Docker Engine | 29.1.3 | Container runtime | M4 |
| Docker Compose plugin | v5.2.0 | Multi-container orchestration | M4 |
| Node.js | v20.20.2 | Frontend JS runtime (build + dev) | M5 |
| npm | 10.8.2 | JS package manager | M5 |
| React + react-dom | ^19.2.7 | UI framework | M5 |
| react-router-dom | ^7.18.0 | Client-side routing | M5 |
| @tanstack/react-query | ^5.101.1 | Server state / data fetching | M5 |
| axios | ^1.18.1 | HTTP client | M5 |
| bootstrap | ^5.3.8 | CSS framework | M5 |
| vite | ^8.1.0 | Frontend build tool + dev server | M5 |
| kubectl | 1.31.x | Kubernetes CLI | M6 |
| kind | 0.24.0 | Local Kubernetes cluster | M6 |
| helm | 3.x | Kubernetes package manager | M6 |
| ingress-nginx (Helm) | latest stable | Ingress controller | M6 |
| cert-manager (Helm) | latest stable | TLS cert automation | M6 |
| loki (Helm) | latest stable | Log aggregation | M6 |
| promtail (Helm) | latest stable | Log collection agent | M6 |
| grafana (Helm) | latest stable | Log visualization | M6 |
