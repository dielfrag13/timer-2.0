# Milestone 5 — Running and Testing

This guide covers two ways to run the full application and a manual test
checklist covering every page and flow delivered in Milestone 5.

---

## Option A — Local Development (recommended for active work)

In local dev, Django and Vite each run as separate processes on the host.
Vite proxies all `/api/` and `/admin/` requests to Django so there are no CORS
issues and no Docker rebuild loop between code changes.

### Prerequisites

- Python `.venv` created and dependencies installed (`pip install -r requirements.txt`)
- Node.js installed via nvm; `node` and `npm` available in the current shell
- PostgreSQL running locally (the same setup used for pytest in M1–M4)
- `backend/.env` has `DATABASE_URL=postgres://timer:password@localhost:5432/timer`
  (the `@localhost:` form, not `@db:`)

### Starting the backend

```bash
cd backend
.venv/bin/python manage.py runserver
```

Django listens on `http://localhost:8000`. Migrations should already be applied;
if not, run `python manage.py migrate` first.

### Starting the frontend

In a second terminal. The `source ~/.nvm/nvm.sh` prefix is required because
Claude's non-interactive shell does not load nvm automatically — omit it if
running from an interactive terminal where nvm is already loaded.

```bash
cd frontend
source ~/.nvm/nvm.sh && npm run dev
```

Vite starts on `http://localhost:5173` (or prints the actual port). Open that
URL in the browser. All `/api/` and `/admin/` requests are forwarded to
`http://localhost:8000` by the Vite dev proxy configured in `vite.config.js`.

### Running the backend tests

```bash
cd backend
.venv/bin/pytest
```

All 72 tests should pass. `DATABASE_URL` must use `@localhost:` for pytest to
reach the local Postgres instance.

---

## Option B — Full Docker Compose Stack

Runs backend + frontend in containers. All traffic goes through nginx on
port 80.

### Prerequisites

- Docker Engine and the Docker Compose v2 plugin installed (`docker compose version`)
- `backend/.env` has `DATABASE_URL=postgres://timer:password@db:5432/timer`
  (the `@db:` form — `db` is the Postgres service hostname inside Docker)

> **Switching between local dev and Docker Compose:** The only change needed
> is the hostname in `DATABASE_URL` in `backend/.env`:
> - Local dev / pytest → `@localhost:5432`
> - Docker Compose → `@db:5432`

### Building and starting

From the repo root:

```bash
docker compose up --build
```

Three containers start in order: `db` → `backend` (waits for Postgres, runs
migrations, starts Gunicorn) → `frontend` (nginx serves the pre-built React
app and proxies API calls to `backend:8000`).

Open `http://localhost` in the browser.

### Creating a superuser (first run)

```bash
docker compose exec backend python manage.py createsuperuser
```

This creates the Django admin account used for the admin login flow below.

### Stopping

```bash
docker compose down        # stops containers, preserves postgres_data volume
docker compose down -v     # stops containers AND deletes all data
```

---

## Setting Up Test Data

Before running the manual checklist, create a minimum data set through the
browser UI (logged in as admin) or via the API.

1. **Log in** as the superuser created above.
2. **Create a Surgeon** (Surgeons page → + New Surgeon). Give them a name and email.
3. **Link a user account** to the surgeon — in the Django admin
   (`http://localhost/admin/` in Docker, `http://localhost:8000/admin/` in local
   dev), find the Surgeon record and set its `user` field to an existing Django
   user. To create a non-admin surgeon user: Django admin → Users → Add user.
4. **Create an Operation Type** (Operation Types page → + New Operation Type).
5. **Create at least two Steps** (Operation Types page → Steps section →
   + New Step). These will be used in the OCS1 step list.

---

## Manual Test Checklist

### 1. Stack health

| Check | Expected |
|---|---|
| `docker compose ps` (Docker) or both dev servers running | backend healthy, frontend up |
| `http://localhost/health/` (Docker) or `http://localhost:8000/health/` (local) | `{"status": "ok"}` |

---

### 2. Login page (`/login`)

| Check | Expected |
|---|---|
| Navigate to `http://localhost` (not logged in) | Redirected to `/login` |
| Submit invalid credentials | Red "Invalid username or password" alert, stays on `/login` |
| Submit valid admin credentials | Redirected to `/` (Dashboard) |
| Navigate to `/login` while already logged in | Immediately redirected to `/` |

---

### 3. Dashboard (`/`)

| Check | Expected |
|---|---|
| No operations exist yet | Both sections empty; "+ Begin Operation" button visible |
| Active operations card | Shows operation type + date; "Setup Steps →" if no `in_room_time`, "Resume Timing →" if set |
| Completed section heading | Shows correct count (e.g. "Completed (3)"), not always 25 |
| Surgeon column visibility | Shown for admin users only |
| "View Stats" link | Navigates to `/operations/:id/stats` |

---

### 4. Surgeons page (`/surgeons`) — admin only link

| Check | Expected |
|---|---|
| Non-admin user | No "Surgeons" link in navbar |
| Admin: visit `/surgeons` | Table shows all surgeons with Name, Email, Username, Actions columns |
| Admin: "+ New Surgeon" | Modal opens; fill name + email + username; Save creates the record |
| Admin: Edit | Modal pre-filled; Save updates the record |
| Admin: Delete | `window.confirm` prompt; confirm removes the row |
| Duplicate email | DRF validation error shown in modal |

---

### 5. Operation Types page (`/operation-types`) — admin only link

| Check | Expected |
|---|---|
| Both Operation Types and Steps sections visible | Table rows for each |
| Admin: create/edit/delete operation type | Works; table updates immediately |
| Admin: create/edit/delete step | Works; note explains steps are global |
| Non-admin: visit `/operation-types` directly | Tables shown; no Add / Edit / Delete buttons |

---

### 6. Begin Operation (`/operations/new`)

| Check | Expected |
|---|---|
| Non-admin with no linked surgeon | Warning message instead of form |
| Non-admin with linked surgeon | Form shown; surgeon field hidden |
| Admin | Surgeon dropdown visible and required |
| Date field default | Today's date pre-filled |
| Submit with no operation type | Browser HTML5 validation prevents submit |
| Valid submit | Creates operation; navigates to `/operations/:id/ocs1` |

---

### 7. OCS1 — Step Setup (`/operations/:id/ocs1`)

| Check | Expected |
|---|---|
| Brand new operation (no history) | "No steps added yet." + empty suggested panel |
| Operation with history | "Suggested from prior history" card shows ordered steps |
| "+ Add All" button | Creates all suggested step instances in order; suggested panel hides |
| "+ Add" on individual suggested step | Adds just that step; order preserved |
| Manual dropdown + Add | Step added to bottom of list |
| Remove button | Removes step instance from list |
| "Enter Room" disabled | While step list is empty |
| "Enter Room" click | PATCHes `in_room_time`; navigates to `/operations/:id/ocs2` |
| Navigate to OCS1 for an already-started operation | Info alert with link to OCS2 |

---

### 8. OCS2 — Live Timing (`/operations/:id/ocs2`)

| Check | Expected |
|---|---|
| "Time in room" clock | Ticks every second; increases continuously |
| Steps with no times | Start column shows "Now" button; End and Elapsed show `—` |
| Click "Now" for Start | Start time set; row highlights blue; End "Now" button appears; Elapsed starts counting |
| Active row while timing | `table-primary` blue highlight on the row with `start_time` but no `end_time` |
| Click "Now" for End | End time set; row de-highlights; Elapsed shows fixed duration |
| Elapsed for completed step | Computed from `end_time - start_time` (not from API until complete) |
| "Complete Operation" disabled | While any step has no end time |
| "Complete Operation" enabled | Once all steps have an end time |
| Click "Complete Operation" | Navigates to `/operations/:id/stats` immediately |
| Navigate to OCS2 for a not-yet-started operation | Warning alert with link to OCS1 |

---

### 9. Post-op Stats (`/operations/:id/stats`)

| Check | Expected |
|---|---|
| Header | Operation type, date, total elapsed (e.g. "42m 15s") |
| Surgeon shown | Admin users only |
| Color coding: green | Steps within 10% of historical average |
| Color coding: yellow | 10–25% deviation |
| Color coding: red | Beyond 25% deviation |
| No color | Steps with no historical data (first time that step has been timed) |
| "vs. Avg" column values | Format `+12.3%` or `-5.1%` with sign; `—` when no history |
| "Download CSV" | Browser downloads a `.csv` file with step data |
| "Back to Dashboard" | Returns to `/` |

---

### 10. Auth and session

| Check | Expected |
|---|---|
| Logout | Navbar "Logout" button → redirected to `/login` |
| Access protected page after logout | Redirected to `/login` |
| Page reload while logged in | Stays on the current page (cookie persists; `/me/` re-authenticates on mount) |
| Direct URL navigation | `/operations/:id/ocs2` etc. work on reload — SPA fallback serves `index.html` and React Router handles the route |

---

## Summary Checklist

| # | Area | Key pass condition |
|---|---|---|
| 1 | Stack | All containers up; health endpoint responds |
| 2 | Login | Invalid creds rejected; valid creds navigate to Dashboard |
| 3 | Dashboard | Active and completed sections populate correctly |
| 4 | Surgeons | Admin CRUD works; non-admin sees no edit controls |
| 5 | Operation Types | Both sections editable by admin; read-only for others |
| 6 | Begin Operation | Admin surgeon dropdown; non-admin surgeon auto-filled |
| 7 | OCS1 | Suggested steps displayed; add/remove works; Enter Room navigates to OCS2 |
| 8 | OCS2 | Clock ticks; Now buttons record times; Complete Operation navigates to Stats |
| 9 | Post-op Stats | Color coding correct; CSV downloads; total elapsed shown |
| 10 | Session | Logout clears session; reload re-authenticates from cookie |
