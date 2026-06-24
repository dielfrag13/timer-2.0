# Milestone 4 — Running and Testing

This guide covers everything needed to build, start, and manually verify the
Milestone 4 deliverables: the Dockerized backend stack running with a single
`docker compose up --build`.

---

## Prerequisites

### Docker and the Compose plugin

Docker Engine and the Docker Compose v2 plugin must both be installed. Verify:

```bash
docker version
docker compose version
```

Both commands must succeed. If `docker compose version` fails, install the
plugin from the official Docker apt repository:

```bash
# Add Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the official Docker apt repository (single line — do not wrap)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install the plugin
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

### Milestones 1–3 complete

The backend code and migrations must be in place. No additional Python setup is
required — Docker handles all of that inside the container.

---

## Environment Setup

`docker-compose.yml` reads secrets from `backend/.env` at runtime. The only
change needed from the local-dev `.env` is the `DATABASE_URL` hostname.

Open `backend/.env` and change `localhost` to `db` in `DATABASE_URL`:

```
# Local dev / pytest:
# DATABASE_URL=postgres://timer:password@localhost:5432/timer

# Docker Compose:
DATABASE_URL=postgres://timer:password@db:5432/timer
```

`db` is the name of the Postgres service in `docker-compose.yml`. Inside the
Docker network, services reach each other by service name — `localhost` inside
the backend container refers to the container itself, not the host machine or
the database container.

> **Switching back to local dev:** change `db` back to `localhost` in `.env`
> before running `pytest` directly on the host.

---

## Building and Starting the Stack

From the repo root (where `docker-compose.yml` lives):

```bash
docker compose up --build
```

The `--build` flag rebuilds the backend image before starting. Omit it on
subsequent starts if the code hasn't changed and you want a faster startup.

To run in the background (detached mode):

```bash
docker compose up --build -d
```

**What happens on first start:**

1. Docker builds the `backend` image from `backend/Dockerfile`
2. Both containers start; the `backend` container waits for Postgres
3. `pg_isready` loops until Postgres accepts connections (usually 2–3 seconds)
4. Django migrations run automatically
5. Gunicorn starts and begins serving requests

Expected log output (visible without `-d`, or via `docker compose logs`):

```
backend-1 | Waiting for Postgres at db:5432...
backend-1 | db:5432 - no response
backend-1 | db:5432 - accepting connections
backend-1 | Postgres ready.
backend-1 | Running migrations...
backend-1 |   Applying timer.0001_initial... OK
backend-1 |   Applying timer.0002_surgeon_user... OK
backend-1 |   Applying token_blacklist.0001_initial... OK
backend-1 | Starting server...
```

---

## Manual Tests

### 1. Container status

```bash
docker compose ps
```

Expected — both containers up, backend marked `(healthy)`:

```
NAME                 STATUS                    PORTS
timer-20-backend-1   Up N seconds (healthy)    0.0.0.0:8000->8000/tcp
timer-20-db-1        Up N seconds              5432/tcp
```

The backend will show `(health: starting)` for up to 15 seconds while the
`start_period` elapses. It should transition to `(healthy)` shortly after
Gunicorn starts.

---

### 2. Health endpoint

```bash
curl -s http://localhost:8000/health/
```

Expected: `{"status": "ok"}`

Also confirm HTTP 200:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health/
```

Expected: `200`

---

### 3. Protected endpoint requires a token

```bash
curl -s http://localhost:8000/api/v1/surgeons/
```

Expected: HTTP 401 — confirms auth is active in the Docker environment.

---

### 4. Login via the API

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<your-password>"}'
```

If no superuser exists yet, create one:

```bash
docker compose run --rm backend python manage.py createsuperuser
```

Expected: HTTP 200 with `access` and `refresh` tokens.

---

### 5. Structured JSON logs

```bash
docker compose logs backend
```

Once Gunicorn is running, every log line after the startup messages should be
valid JSON. Make a request in a second terminal and look for a line like:

```json
{"timestamp": "...", "level": "INFO", "logger": "timer.api", "message": "request",
 "method": "GET", "path": "/health/", "status": 200, "duration_ms": 3}
```

Confirm:
- All post-startup lines are parseable JSON
- Each line contains `timestamp`, `level`, `logger`, and `message` keys

To stream logs live:

```bash
docker compose logs -f backend
```

---

### 6. Migrations only run once

Stop and restart the stack without `--build`:

```bash
docker compose down
docker compose up -d
docker compose logs backend
```

Expected: the migration output shows `No migrations to apply.` (or lists
migrations as already applied with `OK`). Django tracks applied migrations in
the `django_migrations` table, which persists in the named `postgres_data`
volume across restarts.

---

### 7. Data persists across restarts

`docker compose down` removes the containers but **not** the named volume. Data
written in one session is available in the next.

To destroy data and start completely fresh:

```bash
docker compose down -v
```

The `-v` flag removes named volumes. The next `docker compose up` will
re-initialise an empty Postgres database and re-run all migrations.

---

## Stopping the Stack

```bash
docker compose down
```

Stops and removes containers and the network. The `postgres_data` volume is
preserved.

---

## Summary Checklist

| # | Test | Pass condition |
|---|---|---|
| 1 | `docker compose up --build` | Both containers start without errors |
| 2 | `docker compose ps` | backend shows `(healthy)`, db shows `Up` |
| 3 | `GET /health/` | `{"status": "ok"}` with HTTP 200 |
| 4 | `GET /api/v1/surgeons/` unauthenticated | HTTP 401 |
| 5 | Login via API | HTTP 200 with `access` and `refresh` tokens |
| 6 | `docker compose logs backend` | JSON lines with required keys after startup |
| 7 | Restart without `--build` | Migrations skipped (already applied) |
| 8 | `docker compose down` then `up` | Data from previous session still present |
