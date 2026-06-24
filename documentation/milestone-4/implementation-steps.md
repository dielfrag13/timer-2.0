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

**What it is:** A shell script that runs inside the container every time it
starts. Its job is to handle startup sequencing before handing off to Gunicorn.

**Why a separate script rather than inline `CMD`?**
`CMD` in a Dockerfile can only run a single command. Our startup needs several
steps in order, with logic (the wait loop), so a shell script is the natural
choice.

**Waiting for Postgres — the race condition problem**
`docker compose up` starts all services in parallel (modulo `depends_on`).
Even with `depends_on: db`, Compose only waits for the `db` container to
*start* — not for Postgres inside it to finish initialising and accept
connections. The first time the volume is empty, Postgres takes several seconds
to initialise the data directory. If Django tries to run `migrate` before
Postgres is ready, it crashes.

The fix is a `until pg_isready` loop:

```bash
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
  sleep 1
done
```

`pg_isready` is a lightweight tool that probes the Postgres port and returns
exit code 0 only when the server is accepting connections. We loop until it
succeeds.

The host, port, and user are parsed from `DATABASE_URL` so we don't hardcode
connection details in two places.

**Running migrations**
`python manage.py migrate` applies any pending database migrations before
Gunicorn starts serving requests. Running it here (at container startup) rather
than at build time is correct because migrations need a live database, and the
database is only available at runtime.

On subsequent deploys this is idempotent — Django tracks which migrations have
already been applied and skips them.

**Starting Gunicorn**
Gunicorn is the production WSGI server. Key flags:

- `--bind 0.0.0.0:8000` — listen on all interfaces inside the container so
  Docker's network bridge can forward traffic to it.
- `--workers 3` — number of worker processes. A common starting rule of thumb
  is `2 * CPU_cores + 1`; we use 3 as a sensible default for local and
  small-scale production.
- `--access-logfile -` — write Gunicorn's access log to stdout (the `-` means
  stdout). Docker captures everything written to stdout/stderr and makes it
  available via `docker compose logs`.
- `--error-logfile -` — same for Gunicorn's error log.
- `exec` prefix — replaces the shell process with Gunicorn rather than running
  it as a child. This ensures Gunicorn receives OS signals (like SIGTERM from
  `docker stop`) correctly, allowing graceful shutdown.

---

## Step 3 — `backend/.dockerignore`

**What it is:** Works exactly like `.gitignore` but for the Docker build
context. When you run `docker build`, Docker sends everything in the build
directory to the Docker daemon as a tarball (the "build context"). A
`.dockerignore` file tells Docker which paths to exclude from that tarball.

**Why it matters:**
Without `.dockerignore`, Docker would send the entire `backend/` directory to
the daemon, including `.venv/` (hundreds of megabytes of installed packages),
`.git/`, `__pycache__/`, and other files that serve no purpose inside the
image. This makes builds slow and the final image larger.

**Key exclusions:**
- `.venv/` — the local virtual environment. The Dockerfile installs packages
  fresh from `requirements.txt` into the image's system Python; the local venv
  is irrelevant and would massively bloat the build context.
- `__pycache__/` and `*.pyc` — compiled bytecode. Python regenerates these
  inside the container; including them from the host can cause subtle issues if
  the host and container Python versions differ.
- `static_files/` — the output of `collectstatic` on the host. The Dockerfile
  runs `collectstatic` as part of the image build, so the host copy would just
  overwrite it (at best) or cause confusion (at worst).
- `.env` — the local secrets file. It must never be copied into the image.
  Secrets reach the container at runtime via `env_file` in `docker-compose.yml`.
- `.pytest_cache/` and `*.md` test files — not needed at runtime.

---

## Step 4 — `docker-compose.yml`

**What it is:** A YAML file that defines a multi-container application. Running
`docker compose up` reads this file and starts all defined services, creating
the network, volumes, and containers described.

**The `db` service**
Runs the official `postgres:16` image. Key configuration:

- `environment` — sets `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
  These are read by the Postgres image's entrypoint to initialise the database
  on first start.
- `volumes` — mounts a named volume (`postgres_data`) at `/var/lib/postgresql/data`,
  which is where Postgres stores its data files. Named volumes persist across
  `docker compose down` (data survives). Only `docker compose down -v` removes them.
- No exposed ports by default — Postgres is only reachable by other containers
  on the Compose network, not from the host machine. This is a security default;
  we can add `ports: ["5432:5432"]` for local debugging if needed.

**The `backend` service**
- `build: ./backend` — tells Compose to build the image from `backend/Dockerfile`
  rather than pulling a pre-built one.
- `env_file: ./backend/.env` — loads all variables from the `.env` file into
  the container's environment at startup. This is how `SECRET_KEY`, `DATABASE_URL`,
  and other secrets reach Django without being baked into the image.
- `depends_on: db` — Compose starts `db` before `backend`. Combined with the
  `pg_isready` loop in `entrypoint.sh`, this ensures Postgres is always ready
  before Django tries to connect.
- `ports: ["8000:8000"]` — maps port 8000 on the host to port 8000 in the
  container, making the API reachable at `http://localhost:8000` from the host.

**HEALTHCHECK**
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://localhost:8000/health/ || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

Docker's `HEALTHCHECK` periodically runs a command inside the container. If it
returns non-zero, the container is marked `unhealthy`. This is what Kubernetes
(and other orchestrators) use to decide whether to send traffic to the container
or restart it. `start_period` gives the app time to start before health checks
begin counting failures.

We target `GET /health/` because it's the lightest possible check — it confirms
Django loaded, the settings parsed correctly, and the app is listening.

**Named volume declaration**
```yaml
volumes:
  postgres_data:
```

Named volumes must be declared at the top level of `docker-compose.yml`. This
is what makes them persist between `docker compose down` restarts.

---

## Step 5 — Update `backend/.env.example`

The current `.env.example` has `DATABASE_URL` pointing to `localhost`. This is
correct when running Django directly on the host (for development and tests),
but wrong when running inside Docker Compose. Inside the `backend` container,
`localhost` refers to the container itself — not the host machine, and not the
`db` container.

In Docker Compose, each service is reachable by its **service name** on the
shared Compose network. The Postgres service is named `db`, so the correct
`DATABASE_URL` inside Docker is:

```
DATABASE_URL=postgres://timer:password@db:5432/timer
```

We'll add a clearly commented block to `.env.example` documenting both variants
so it's obvious which value to use in each context.

---

## Step 6 — Smoke test: `docker compose up --build`

Before writing documentation, verify the stack actually works end-to-end:

1. Build and start both services: `docker compose up --build`
2. Confirm the backend container becomes `healthy` (visible in `docker compose ps`)
3. Confirm `GET /health/` returns `{"status": "ok"}` from the host
4. Confirm `docker compose logs backend` shows structured JSON lines
5. Confirm migrations ran successfully (visible in the startup logs)

Any failures here get diagnosed and fixed before moving to Step 7.

---

## Step 7 — Update `milestones.md` and add `documentation/milestone-4/running-and-testing.md`

Mark M4 as Complete in `milestones.md`.

Write `documentation/milestone-4/running-and-testing.md` covering:
- Prerequisites (Docker installed, `.env` updated for Docker)
- Building and starting the stack (`docker compose up --build`)
- Verifying the health check and container status
- Inspecting unified logs
- Stopping the stack and data persistence behaviour
- Summary checklist
