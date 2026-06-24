# Milestone 4 — Implementation Steps

Concrete steps for containerizing the backend so the full stack starts with a
single `docker compose up --build`. Each step explains not just what to do but
why it works the way it does.

---

## Step 1 — `backend/Dockerfile`

**Status: Complete** — file at `backend/Dockerfile`

**What it is:** A `Dockerfile` is a recipe that tells Docker how to build a
self-contained image — a snapshot of an operating system, runtime, dependencies,
and your application code. Running a container from that image is like booting a
tiny, isolated Linux machine that already has everything installed.

**Base image — `python:3.12-slim`**
Docker images are built in layers, always starting from a parent image. We use
`python:3.12-slim`, which is an official Debian-based image with Python 3.12
pre-installed and most non-essential packages stripped out to keep the image
small. The `slim` variant omits compilers, documentation, and locale data —
everything we don't need at runtime.

**System packages**
Even though `python:3.12-slim` is stripped down, two system packages are still
needed and must be installed via `apt-get`:

- `postgresql-client` — provides the `pg_isready` command used in
  `entrypoint.sh` to wait for Postgres before starting the app. Without this,
  the entrypoint has no reliable way to know when the database is ready.
- `curl` — used by the Docker `HEALTHCHECK` in `docker-compose.yml` to probe
  `GET /health/` on each interval. The slim base image does not include curl.

Both are installed in a single `RUN` layer with `--no-install-recommends` to
avoid pulling in unnecessary extras, and the apt cache is deleted in the same
layer (`rm -rf /var/lib/apt/lists/*`) to keep the image small. Doing both in
one `RUN` command is important: each `RUN` creates a new image layer, so if
we deleted the cache in a separate layer it would have no effect — the cache
would already be baked into the previous layer.

**Installing Python dependencies**
Dependencies are copied and installed before the application source code. This
is a deliberate Docker caching strategy: Docker caches each layer separately,
and only re-executes a layer if it or anything before it changed. Copying
`requirements.txt` first means Docker can reuse the expensive `pip install`
layer on rebuilds as long as `requirements.txt` hasn't changed, even if the
application code has.

**Running `collectstatic` at build time**
Django's `collectstatic` command gathers all static files (CSS, JS, admin
assets) from all installed apps into a single `STATIC_ROOT` directory so they
can be served efficiently. It must run at build time (not startup) because:
1. Static files are the same for every instance — they belong in the image.
2. Running it at startup would slow container startup on every deploy.

`collectstatic` loads Django settings to discover which apps have static files,
which means the full settings module must be loadable. Our settings require two
environment variables with no defaults — `SECRET_KEY` and `DATABASE_URL`. The
real values are runtime secrets and must not be baked into the image, so we
pass throwaway values just for this build step:

```dockerfile
RUN SECRET_KEY=dummy-for-collectstatic \
    DATABASE_URL=postgres://none:none@localhost/none \
    python manage.py collectstatic --noinput
```

`collectstatic` never actually connects to the database, so the dummy
`DATABASE_URL` is never used for a real connection — it just needs to be a
valid URL so `django-environ` can parse it without erroring. The `--noinput`
flag suppresses the confirmation prompt so the build doesn't hang waiting for
keyboard input.

**Entrypoint and default command**
`ENTRYPOINT` sets the script that always runs when the container starts.
`CMD` sets the default arguments passed to it (which Gunicorn will receive).
Separating them lets `docker run` callers override the command without
replacing the entrypoint, which is useful for running one-off management
commands (`docker compose run backend python manage.py createsuperuser`).

The final Dockerfile:

```dockerfile
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-client \
       curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=dummy-for-collectstatic \
    DATABASE_URL=postgres://none:none@localhost/none \
    python manage.py collectstatic --noinput

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "timer_server.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

---

## Step 2 — `backend/entrypoint.sh`

**Status: Complete** — file at `backend/entrypoint.sh`

**What it is:** A shell script that runs inside the container every time it
starts. Its job is to handle startup sequencing before handing off to Gunicorn.

**Why a separate script rather than inline `CMD`?**
`CMD` in a Dockerfile can only run a single command. Our startup needs several
steps in order, with logic (the wait loop), so a shell script is the natural
choice.

**`set -e` at the top**
This tells bash to exit immediately if any command returns a non-zero exit code.
Without it, if `migrate` fails (e.g. because of a bad migration), the script
would continue and start Gunicorn anyway — serving requests against a broken
database schema. `set -e` ensures the container crashes loudly and Docker marks
it as failed rather than silently starting a broken app.

**Waiting for Postgres — the race condition problem**
`docker compose up` starts all services in parallel (modulo `depends_on`).
Even with `depends_on: db`, Compose only waits for the `db` container to
*start* — not for Postgres inside it to finish initialising and accept
connections. The first time the volume is empty, Postgres takes several seconds
to initialise the data directory. If Django tries to run `migrate` before
Postgres is ready, it crashes.

The fix is an `until pg_isready` loop:

```bash
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  sleep 1
done
```

`pg_isready` is a lightweight tool that probes the Postgres port and returns
exit code 0 only when the server is accepting connections. We loop with a 1s
sleep until it succeeds.

**Parsing `DATABASE_URL` rather than hardcoding**
The host, port, and user are extracted from `DATABASE_URL` using Python's
`urllib.parse.urlparse`. This means connection details only live in one place
(the `.env` file) rather than being duplicated in the entrypoint script:

```bash
DB_HOST=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.hostname)")
DB_PORT=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.port or 5432)")
DB_USER=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.username)")
```

Python is already available in the container and is a more reliable URL parser
than bash string manipulation.

**Running migrations**
`python manage.py migrate` applies any pending database migrations before
Gunicorn starts serving requests. Running it here (at container startup) rather
than at build time is correct because migrations need a live database, and the
database is only available at runtime.

On subsequent deploys this is idempotent — Django tracks which migrations have
already been applied and skips them. The cost is a few hundred milliseconds on
startup, which is acceptable.

**`exec "$@"` — handing off to Gunicorn**
`$@` expands to all arguments passed to the script. Because the Dockerfile sets:

```dockerfile
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "timer_server.wsgi:application", "--bind", "0.0.0.0:8000", ...]
```

Docker calls `./entrypoint.sh gunicorn timer_server.wsgi:application ...` — so
`$@` is the full Gunicorn command.

`exec` is critical: it *replaces* the shell process with Gunicorn rather than
spawning Gunicorn as a child process. Without `exec`, the process tree would be:

```
PID 1: bash (entrypoint.sh)
  └─ PID 2: gunicorn
```

With `exec`, Gunicorn *becomes* PID 1 (inheriting the shell's PID). This
matters because Docker sends `SIGTERM` to PID 1 when you run `docker stop`.
If bash is PID 1, it may not forward the signal to Gunicorn, preventing
graceful shutdown. With `exec`, Gunicorn receives SIGTERM directly and can
finish in-flight requests before exiting.

The final entrypoint.sh:

```bash
#!/usr/bin/env bash
set -e

DB_HOST=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.hostname)")
DB_PORT=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.port or 5432)")
DB_USER=$(python -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ['DATABASE_URL']); print(u.username)")

echo "Waiting for Postgres at $DB_HOST:$DB_PORT..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  sleep 1
done
echo "Postgres ready."

echo "Running migrations..."
python manage.py migrate

echo "Starting server..."
exec "$@"
```

---

## Step 3 — `backend/.dockerignore`

**Status: Complete** — file at `backend/.dockerignore`

**What it is:** Works exactly like `.gitignore` but for the Docker build
context. When you run `docker build` (or `docker compose up --build`), Docker
bundles everything in the build directory into a tarball and sends it to the
Docker daemon — this is called the "build context". A `.dockerignore` file
tells Docker which paths to leave out of that tarball before it's sent.

**Why it matters:**
Without `.dockerignore`, Docker would send the entire `backend/` directory to
the daemon, including `.venv/` (hundreds of megabytes of installed packages)
and `__pycache__/`. This makes builds slow because: (1) the tarball takes time
to assemble and transfer, and (2) large contexts increase the chance of
accidentally busting the pip install cache layer when unrelated files change.

**Why `.git` isn't listed**
The build context for the `backend` service in `docker-compose.yml` is
`./backend` — so Docker only sends the contents of the `backend/` directory.
The `.git` directory lives at the repo root, outside that scope, so it's
never included in the first place.

**Key exclusions and why each one matters:**

- `.venv/` — the local virtual environment is hundreds of megabytes and is
  entirely irrelevant inside the image. The Dockerfile runs `pip install`
  against the image's system Python, building a fresh environment from
  `requirements.txt`. Including the local venv would bloat the build context
  enormously for zero benefit.

- `__pycache__/` and `*.pyc`/`*.pyo` — compiled Python bytecode. Python
  regenerates `.pyc` files automatically when it runs `.py` files. Including
  host-compiled bytecode can cause subtle issues if the host Python version
  doesn't exactly match the container's Python version (the bytecode format
  differs between minor versions).

- `static_files/` — the output directory of `collectstatic` on the host
  machine. The Dockerfile runs `collectstatic` as part of the image build
  step, producing a fresh copy inside the image. If the host copy were
  included in the build context, it would either overwrite the freshly-built
  copy or, depending on ordering, cause confusion about which version is
  canonical.

- `.env` — the secrets file. This is the most security-critical exclusion.
  The `.env` file contains `SECRET_KEY`, database credentials, and other
  sensitive values. If it were copied into the image, those secrets would be
  permanently embedded in every layer of the image — visible to anyone who
  pulls or inspects it. Secrets must reach the container exclusively at
  runtime via `env_file` in `docker-compose.yml`.

- `.pytest_cache/`, `conftest.py`, `pytest.ini`, `requirements-dev.txt` —
  test infrastructure. None of these are needed at runtime. Excluding them
  keeps the image lean and ensures the production image can't accidentally
  run tests.

The final `.dockerignore`:

```
.venv/
__pycache__/
*.pyc
*.pyo
static_files/
.env
.pytest_cache/
conftest.py
pytest.ini
requirements-dev.txt
```

---

## Step 4 — `docker-compose.yml`

**Status: Complete** — file at `docker-compose.yml` (repo root)

**What it is:** A YAML file that defines a multi-container application. Running
`docker compose up` reads this file and starts all defined services, creating
the shared network, volumes, and containers described. It is placed at the repo
root (not inside `backend/`) because it will eventually orchestrate multiple
services — the backend now, the frontend in Milestone 5.

**The `db` service**
Runs the official `postgres:16` image. Key configuration:

- `environment` — sets `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
  These are read by the Postgres image's own entrypoint script to initialise
  the database cluster on the very first start (when the volume is empty).
  On subsequent starts the volume already contains data, so these vars are
  ignored.
- `volumes` — mounts a named volume (`postgres_data`) at
  `/var/lib/postgresql/data`, which is where Postgres stores its data files.
  Named volumes are managed by Docker and live outside the container filesystem,
  so they survive `docker compose down`. Only `docker compose down -v` removes
  them (destroying all data). This is the correct choice for a database.
- `restart: unless-stopped` — Docker will automatically restart the container
  if it crashes, unless you explicitly stopped it with `docker compose stop`.
- No `ports` on `db` — Postgres is only reachable by other containers on the
  Compose-managed internal network, not from the host machine. This is a
  security default; you can temporarily add `ports: ["5432:5432"]` for direct
  psql access during debugging.

**The `backend` service**
- `build: ./backend` — tells Compose to build the image from `backend/Dockerfile`
  rather than pulling a pre-built one from a registry. On `docker compose up
  --build` Docker rebuilds; on plain `docker compose up` it reuses the cached
  image.
- `env_file: ./backend/.env` — reads every line from the `.env` file and injects
  it as an environment variable in the container at runtime. This is the mechanism
  by which `SECRET_KEY`, `DATABASE_URL`, `LOG_LEVEL`, etc. reach Django without
  ever being baked into the image.
- `depends_on: db` — Compose starts `db` before attempting to start `backend`.
  Note: this only guarantees the `db` *container* starts, not that Postgres is
  ready to accept connections. The `pg_isready` loop in `entrypoint.sh` handles
  the remaining gap.
- `ports: ["8000:8000"]` — the format is `"host_port:container_port"`. This
  maps port 8000 on your machine to port 8000 inside the container, making the
  API reachable at `http://localhost:8000` from the host.
- `restart: unless-stopped` — same crash-restart behaviour as `db`.

**HEALTHCHECK**
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://localhost:8000/health/ || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

Docker's `HEALTHCHECK` periodically runs a command *inside* the container and
uses the exit code to decide the container's health status (`healthy`,
`unhealthy`, or `starting`). Field meanings:

- `test` — the command to run. `curl -f` returns a non-zero exit code on HTTP
  errors (4xx, 5xx), so a broken Django app will correctly produce `unhealthy`.
- `interval: 30s` — how often to run the check once the container is running.
- `timeout: 5s` — if the command takes longer than this, it counts as a failure.
- `retries: 3` — the container is only marked `unhealthy` after this many
  consecutive failures.
- `start_period: 15s` — failures during this initial window don't count toward
  `retries`. This gives the entrypoint time to wait for Postgres and run
  migrations before health checks start being judged.

**Named volume declaration**
```yaml
volumes:
  postgres_data:
```

Named volumes must be declared at the top level of `docker-compose.yml`. The
empty value (`postgres_data:`) tells Compose to manage this volume using
Docker's default local driver — data is stored on the host filesystem under
Docker's storage area and persists independently of the containers.

The final `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: timer
      POSTGRES_PASSWORD: password
      POSTGRES_DB: timer
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  backend:
    build: ./backend
    env_file: ./backend/.env
    ports:
      - "8000:8000"
    depends_on:
      - db
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health/ || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

volumes:
  postgres_data:
```

---

## Step 5 — Update `backend/.env.example`

**Status: Complete** — file at `backend/.env.example`

**The problem: `localhost` means different things depending on context**

The existing `.env.example` had:

```
DATABASE_URL=postgres://timer:password@localhost:5432/timer
```

This is correct when running Django directly on the host machine (local dev,
`pytest`), because `localhost` resolves to the host machine where Postgres is
also running.

However, when Django runs *inside a Docker container*, `localhost` resolves to
the container's own loopback interface — not the host machine, and not any
other container. There is no Postgres running inside the `backend` container,
so the connection would fail immediately.

**How Docker Compose networking works**

Every service defined in `docker-compose.yml` is automatically placed on a
shared virtual network that Compose creates. On this network, each service is
resolvable by its **service name** as a hostname. Our Postgres service is named
`db`, so from inside the `backend` container, the database is reachable at
`db:5432`. This is why the Docker variant of `DATABASE_URL` uses `@db:` instead
of `@localhost:`.

**What we changed**

Added a clearly commented explanation of both variants directly above the
`DATABASE_URL` line so there's no ambiguity about which value to use:

```
# Use this value when running Django directly on the host (local dev, pytest):
#   DATABASE_URL=postgres://timer:password@localhost:5432/timer
#
# Use this value when running via docker compose (the host is the service name):
#   DATABASE_URL=postgres://timer:password@db:5432/timer
DATABASE_URL=postgres://timer:password@localhost:5432/timer
```

The default value is left as `localhost` so the file works out of the box for
local development without editing. When switching to Docker, the user updates
this one line in their `.env`.

---

## Step 6 — Smoke test: `docker compose up --build`

**Status: Complete** — stack verified working end-to-end

Before writing documentation, the stack was verified end-to-end. Key results:

**Build output (all 8 layers succeeded):**
- Layer 2: system packages installed (`postgresql-client`, `curl`)
- Layer 5: all Python packages installed from `requirements.txt`
- Layer 7: `collectstatic` ran successfully — `154 static files copied to '/app/static_files'`
- Layer 8: `entrypoint.sh` marked executable

**Container startup (`docker compose ps`):**
```
NAME                 STATUS                    PORTS
timer-20-backend-1   Up 33 seconds (healthy)   0.0.0.0:8000->8000/tcp
timer-20-db-1        Up 33 seconds             5432/tcp
```
Both containers up; backend reached `(healthy)` status within the `start_period`.

**Health endpoint:**
```bash
curl -s http://localhost:8000/health/
# {"status": "ok"}
```

**Startup log sequence (confirming correct ordering):**
```
backend-1 | Waiting for Postgres at db:5432...
backend-1 | db:5432 - no response       ← pg_isready loop fired twice
backend-1 | db:5432 - no response
backend-1 | db:5432 - accepting connections
backend-1 | Postgres ready.
backend-1 | Running migrations...
backend-1 |   Applying timer.0001_initial... OK
backend-1 |   Applying timer.0002_surgeon_user... OK
backend-1 |   Applying token_blacklist.0001_initial... OK
backend-1 | Starting server...
```
The wait loop fired twice before Postgres was ready — confirming the race
condition is real and the loop is doing its job.

**`.env` management during the smoke test**
`DATABASE_URL` was temporarily changed from `@localhost:` to `@db:` for the
Docker run, then reverted to `@localhost:` afterward so `pytest` continues to
work against the local Postgres instance. See implementation-notes.md for more
detail on this dual-context problem.

---

## Step 7 — Update `milestones.md` and add `documentation/milestone-4/running-and-testing.md`

**Status: Complete**

- `documentation/milestones.md` — M4 marked Complete
- `documentation/milestone-4/running-and-testing.md` created covering:
  - Prerequisites (Docker Engine + Compose plugin, including full install
    commands for the official Docker apt repository)
  - `.env` setup for Docker (`@localhost` → `@db`) with a note on switching
    back for local dev
  - `docker compose up --build` walkthrough with expected log output
  - 8 manual tests: container status, health endpoint, auth enforcement, login,
    JSON log verification, migration idempotency, and data persistence across
    restarts
  - How to fully reset with `docker compose down -v`
  - Summary checklist table
