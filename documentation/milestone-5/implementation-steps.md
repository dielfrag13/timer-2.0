# Milestone 5 — Implementation Steps

## Step 1 — Scaffold `frontend/` with Vite + React

**Status: Planned**

Create the React project inside the repo root:

```bash
npm create vite@latest frontend -- --template react
cd frontend && npm install
npm install react-router-dom axios @tanstack/react-query bootstrap
```

Configure the Vite dev proxy in `vite.config.js` so all `/api/` requests from
the browser are forwarded to Django running on port 8000 — this makes the
browser see a single origin and eliminates CORS entirely in development.

Set up the source folder structure:
- `src/api/` — axios client and per-resource request functions
- `src/pages/` — one file per route/page
- `src/components/` — shared UI components (Layout, PrivateRoute, etc.)
- `src/context/` — React context providers (AuthContext)

`main.jsx` bootstraps `QueryClientProvider` (React Query), `BrowserRouter`
(React Router), and imports Bootstrap CSS. `App.jsx` defines the route tree
with placeholder components for each page.

---

## Step 2 — Backend: cookie-based auth endpoints

**Status: Planned**

The existing auth views return tokens in the JSON response body — correct for
API clients but insufficient for a browser frontend, where storing tokens in
JavaScript-accessible storage (localStorage, state) exposes them to XSS.

New views added to `timer/views.py`:

- **`CookieTokenObtainPairView`** — extends `AuditedTokenObtainPairView`.
  After a successful login, calls `response.set_cookie()` to issue both the
  access and refresh tokens as `HttpOnly; SameSite=Lax` cookies. The JSON
  body is preserved so existing tests keep passing.

- **`CookieTokenRefreshView`** — reads the refresh token from the cookie
  (not the request body), generates a new access token, and sets it as a
  fresh cookie. Handles the case where the cookie is absent.

- **`LogoutView`** updated — in addition to blacklisting the refresh token,
  calls `response.delete_cookie()` to clear both cookies from the browser.
  Falls back to the request body if the cookie is absent (keeps API client
  compatibility).

- **`MeView`** — `GET /api/v1/auth/me/`. Returns `{id, username, is_staff}`
  for the currently authenticated user. The frontend calls this on startup
  to determine login state without being able to read the httpOnly cookie.

New URLs wired in `timer_server/urls.py` (cookie variants at the same paths;
existing endpoints removed or replaced).

---

## Step 3 — Axios client + AuthContext + app shell

**Status: Planned**

**`src/api/client.js`** — axios instance configured with:
- `baseURL: '/api/v1/'`
- `withCredentials: true` (sends cookies on every request)
- Response interceptor: on 401, attempt `POST /api/v1/auth/refresh/` (the
  server reads the cookie automatically), then retry the original request.
  If refresh also returns 401, dispatch a logout event and redirect to
  `/login`.

**`src/context/AuthContext.jsx`** — React context providing:
- `user` — `{id, username, is_staff}` or `null`
- `isLoading` — true while the initial `/me/` call is in flight
- `login(username, password)` — POSTs credentials, server sets cookies, calls
  `/me/` to populate `user`
- `logout()` — POSTs to logout endpoint (cookies cleared server-side), clears
  `user`

**`src/components/PrivateRoute.jsx`** — renders children if `user` is set;
redirects to `/login` if `user` is null and loading is complete.

**`src/components/Layout.jsx`** — page shell with a navbar showing the
logged-in username and a logout button. Wraps all authenticated routes.

**`App.jsx`** — route tree:
- `/login` — public
- All other paths — wrapped in `PrivateRoute` and `Layout`

---

## Step 4 — Login page

**Status: Planned**

`src/pages/Login.jsx`:
- Bootstrap card with username and password fields
- Calls `auth.login()` on submit
- Shows a dismissable error alert on bad credentials
- Redirects to `/` on success
- If already authenticated (user in context), redirects immediately to `/`

---

## Step 5 — Surgeon management page

**Status: Planned**

`src/pages/Surgeons.jsx`:
- Fetches `GET /api/v1/surgeons/` via React Query (`useQuery`)
- Displays a Bootstrap table with first name, last name, email, and linked
  username (if any)
- Admin users see "Add Surgeon" button and per-row Edit / Delete controls
- Create and edit use a Bootstrap modal with a controlled form; mutate via
  React Query `useMutation` with cache invalidation on success
- Non-admin users see the list read-only (no create/edit/delete controls)

---

## Step 6 — Operation Types page

**Status: Planned**

`src/pages/OperationTypes.jsx`:
- Fetches `GET /api/v1/operation-types/` and `GET /api/v1/steps/`
- Lists operation types; admins get Add / Edit / Delete
- A nested panel per operation type shows all globally defined Steps (since
  steps are global in the data model, not per-operation-type)
- Admin can create new Step records from this page as well

---

## Step 7 — Dashboard

**Status: Planned**

`src/pages/Dashboard.jsx`:
- Landing page after login
- Fetches `GET /api/v1/operation-instances/?complete=false` filtered to the
  current user (data isolation is enforced by the backend)
- Shows in-progress operations as cards linking to OCS2
- Shows a count of completed operations with a link to a full list
- Prominent "Begin Operation" button navigating to `/operations/new`
- Admin users see all surgeons' operations

---

## Step 8 — Begin Operation form

**Status: Planned**

`src/pages/BeginOperation.jsx`:
- Date field (defaults to today)
- Operation type dropdown (fetched from `/api/v1/operation-types/`)
- Surgeon dropdown — pre-filled and read-only for non-admin users (their own
  surgeon record); selectable for admins
- Optional detail/notes text area
- POSTs to `/api/v1/operation-instances/`
- On success: navigates to `/operations/:id/ocs1`

---

## Step 9 — OCS1: step setup

**Status: Planned**

`src/pages/OCS1.jsx` (route: `/operations/:id/ocs1`):
- Fetches the `OperationInstance` to confirm it is not yet complete and has
  no `in_room_time` set
- Fetches suggested steps from `GET /api/v1/operation-instances/:id/suggested-steps/`
- Displays the suggested step list with order numbers
- "Add Step" control to append additional StepInstances via
  `POST /api/v1/step-instances/`
- "Remove" button per step (deletes the StepInstance)
- "Enter Room" button:
  - PATCHes `{in_room_time: <current HH:MM:SS>}` to the OperationInstance
  - Navigates to `/operations/:id/ocs2`

---

## Step 10 — OCS2: live timing

**Status: Planned**

`src/pages/OCS2.jsx` (route: `/operations/:id/ocs2`):
- Fetches the OperationInstance and its StepInstances on mount
- Displays a running elapsed clock since `in_room_time` using `setInterval`
  (updated every second)
- Step list, one row per StepInstance, showing:
  - Step title
  - Start time (blank if not recorded) + "Start" Now button
  - End time (blank if not recorded) + "End" Now button
  - Elapsed time (computed live from start_time once end_time is set)
- "Now" buttons PATCH `{start_time: <current time>}` or `{end_time: <current time>}`
  to the StepInstance; React Query invalidates and refetches after each mutation
- Highlights the currently active step (has start_time but no end_time)
- "Complete Operation" button (enabled once all steps have an end_time):
  - POSTs to `/api/v1/operation-instances/:id/complete/`
  - Navigates to `/operations/:id/stats`

---

## Step 11 — Post-op stats page

**Status: Planned**

`src/pages/PostOpStats.jsx` (route: `/operations/:id/stats`):
- Fetches `GET /api/v1/operation-instances/:id/` (returns the detail serializer
  with nested step instances including `dist_from_average`)
- Summary header: surgeon name, operation type, date, total elapsed time
- Bootstrap table with one row per StepInstance:
  - Step title, start time, end time, elapsed time (seconds), dist_from_average (%)
- Row color coding via Bootstrap contextual classes:
  - `table-success` — `|dist_from_average| < 10%`
  - `table-warning` — 10% to 25%
  - `table-danger` — beyond 25%
  - No color — `dist_from_average` is null (insufficient historical data)
- "Download CSV" link → `GET /api/v1/operation-instances/:id/export-csv/`
- "Back to Dashboard" link

---

## Step 12 — Frontend Dockerfile (multi-stage) + nginx + docker-compose.yml

**Status: Planned**

**`frontend/Dockerfile`** (multi-stage):
```
Stage 1 — build:
  FROM node:20-alpine
  WORKDIR /app
  COPY package*.json ./
  RUN npm ci
  COPY . .
  RUN npm run build

Stage 2 — serve:
  FROM nginx:alpine
  COPY nginx.conf /etc/nginx/conf.d/default.conf
  COPY --from=build /app/dist /usr/share/nginx/html
  EXPOSE 80
```

**`frontend/nginx.conf`**:
- `location /api/` — proxy_pass to `http://backend:8000`
- `location /admin/` — proxy_pass to `http://backend:8000`
- `location /` — `try_files $uri $uri/ /index.html` (SPA fallback so React
  Router handles client-side navigation on direct URL loads)

**`docker-compose.yml`** update:
- Add `frontend` service built from `./frontend`
- Expose port 80 on the host (`"80:80"`)
- `depends_on: backend`
- Backend port mapping (`8000:8000`) removed — browser traffic now flows
  through nginx only

---

## Step 13 — Docs: milestones.md + milestone-5/ directory

**Status: Planned**

- Mark M5 Complete in `documentation/milestones.md`
- Create `documentation/milestone-5/running-and-testing.md` covering:
  - Local dev (Vite dev server + Django dev server)
  - Full Docker Compose stack
  - Manual test checklist for every page and flow
