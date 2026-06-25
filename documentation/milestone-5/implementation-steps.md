# Milestone 5 — Implementation Steps

## Step 1 — Scaffold `frontend/` with Vite + React

**Status: Complete**

Created the React project and installed all dependencies:

```bash
npm create vite@latest frontend -- --template react
cd frontend && npm install
npm install react-router-dom axios @tanstack/react-query bootstrap
```

**`vite.config.js`** — added dev proxy:
```js
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/admin': 'http://localhost:8000',
  },
},
```

**Source folder structure created:**
- `src/api/` — axios client and per-resource request functions
- `src/pages/` — one file per route/page
- `src/components/` — shared UI components (Layout, PrivateRoute, etc.)
- `src/context/` — React context providers (AuthContext)

**`src/main.jsx`** — bootstraps `QueryClientProvider` (React Query),
`BrowserRouter` (React Router), and imports Bootstrap CSS. All three wrappers
live here so every component in the tree can access them:
```jsx
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
```

**`src/App.jsx`** — defines the full route tree with `Placeholder` components
for every page. Routes with `:id` segments (e.g. `/operations/:id/ocs2`) make
the operation ID available to the page component via React Router's
`useParams()` hook.

**`src/index.css`** — stripped down to `body { margin: 0; }`. All styling will
come from Bootstrap classes.

**`.gitignore`** — added `node_modules/` and `frontend/dist/` at repo root so
neither the installed packages nor the production build are committed.

---

## Step 2 — Backend: cookie-based auth endpoints

**Status: Complete**

New file `timer/authentication.py` — `CookieJWTAuthentication` extends
`JWTAuthentication` to try the `Authorization` header first (all existing
behavior preserved), then fall back to the `timer_access` cookie. Wired into
`settings.py` as the sole `DEFAULT_AUTHENTICATION_CLASSES` entry.

Changes to `timer/views.py`:

- **`_set_auth_cookies(response)`** — helper that reads TTLs from
  `settings.SIMPLE_JWT` and attaches `timer_access` and `timer_refresh` as
  `HttpOnly; SameSite=Lax` cookies. `secure=not settings.DEBUG` so cookies are
  plain HTTP in dev and HTTPS-only in production.

- **`_clear_auth_cookies(response)`** — helper that calls `delete_cookie()`
  for both cookie names.

- **`AuditedTokenObtainPairView`** — unchanged login logic; `_set_auth_cookies`
  called on the response before returning. JSON body preserved so existing
  tests keep passing.

- **`CookieTokenRefreshView`** — new `APIView` (`AllowAny`). Reads the refresh
  token from the `timer_refresh` cookie first, falls back to the request body.
  Uses `TokenRefreshSerializer` directly (mirrors what `TokenRefreshView` does
  internally), catches `TokenError` and re-raises as `InvalidToken` (a DRF
  `APIException` that produces a 401). Sets fresh cookies on success.

- **`LogoutView`** — updated to read refresh from cookie OR body; clears both
  cookies on the response after blacklisting.

- **`MeView`** — new `APIView`. `GET /api/v1/auth/me/` returns
  `{id, username, is_staff}` for the authenticated user. Used by the React
  `AuthContext` on startup to determine login state without being able to read
  the httpOnly cookie.

Changes to `timer_server/urls.py`:
- `TokenRefreshView` replaced with `CookieTokenRefreshView`
- `/api/v1/auth/me/` added

Changes to `timer/tests/test_auth.py`:
- `test_unauthenticated_logout_returns_401` — added `api_client.cookies.clear()`
  before the unauthenticated request (see implementation-notes.md for detail).

---

## Step 3 — Axios client + AuthContext + app shell

**Status: Complete**

**`src/api/client.js`** — axios instance configured with:
- `baseURL: '/api/v1/'`
- `withCredentials: true` (sends cookies on every request automatically)
- Response interceptor: on 401 from a non-auth endpoint that hasn't already
  been retried, POSTs to `/auth/refresh/` (server reads the `timer_refresh`
  cookie and issues a fresh `timer_access` cookie), then retries the original
  request. If refresh also fails, does a hard redirect to `/login`.
- `isRefreshing` flag prevents multiple concurrent 401s from each firing their
  own refresh call.

**`src/context/AuthContext.jsx`** — React context providing:
- `user` — `{id, username, is_staff}` or `null`
- `isLoading` — `true` while the initial `/auth/me/` call is in flight on mount
- `login(username, password)` — POSTs credentials (server sets cookies), then
  calls `/auth/me/` to populate `user` state
- `logout()` — POSTs to `/auth/logout/` (server clears cookies), sets `user`
  to `null`

**`src/components/PrivateRoute.jsx`** — uses React Router's `<Outlet />`
pattern. Shows a loading state while `isLoading` is true, redirects to
`/login` if `user` is null, otherwise renders `<Outlet />` so the matched
child route is displayed.

**`src/components/Layout.jsx`** — navbar with the app name, a Dashboard link,
admin-only Surgeons and Operation Types links (shown only when
`user.is_staff`), the logged-in username, and a Logout button. Renders
`<Outlet />` for the page content below the navbar.

**`src/App.jsx`** — updated to use React Router v6 nested routes:
```
<AuthProvider>
  <Route path="/login" />          ← public
  <Route element={<PrivateRoute />}>
    <Route element={<Layout />}>
      <Route path="/" />           ← all authenticated pages
      <Route path="/surgeons" />
      ...
    </Route>
  </Route>
</AuthProvider>
```
`AuthProvider` wraps everything so any component in the tree can call
`useAuth()`. The two-level nesting (`PrivateRoute` → `Layout`) keeps the auth
guard and the visual shell as separate concerns.

---

## Step 4 — Login page

**Status: Complete**

`src/pages/Login.jsx`:
- Returns `null` while `isLoading` is true (prevents a flash of the login
  form for already-authenticated users while the initial `/me/` call is in
  flight)
- `useEffect` redirects to `/` if `user` is set and loading is complete
- Controlled form with `username` and `password` state
- `isSubmitting` flag disables the button and changes its label to
  "Signing in…" during the request
- On submit: calls `auth.login()`, navigates to `/` on success, sets `error`
  state on failure
- Dismissable Bootstrap `alert-danger` for invalid credentials
- Bootstrap card centered in a full-height light-grey background
  (`min-vh-100 d-flex align-items-center justify-content-center bg-light`)

`App.jsx` updated to import and use the real `Login` component instead of
the `Placeholder`.

---

## Step 5 — Surgeon management page

**Status: Complete**

**Backend changes:**
- `SurgeonSerializer` — added `username` as a `SerializerMethodField` that
  returns `obj.user.username` if a user is linked, otherwise `null`
- `SurgeonViewSet` — added `select_related('user')` to the queryset to avoid
  an N+1 query when serializing the username for each surgeon

**`src/pages/Surgeons.jsx`:**
- `useQuery(['surgeons'])` — fetches `GET /api/v1/surgeons/`, reads
  `r.data.results` (paginated response)
- Bootstrap table with Name, Email, Username (shows `—` when null) columns;
  admin users get a fourth Actions column with Edit and Delete buttons
- Single `saveMutation` handles both create (`POST`) and edit (`PATCH`) — the
  distinction is whether `editTarget` state is null or a surgeon object
- `deleteMutation` fires on confirmed `window.confirm()` to prevent accidental
  deletes; button is disabled while the mutation is pending
- Modal rendered via React state (`showModal` boolean) — no Bootstrap JS
  needed; `modal show d-block` + `modal-backdrop show` classes handle the
  visual appearance
- `setField` helper uses the input's `name` attribute to update the right key
  in `form` state — one function handles all three fields instead of three
  separate `onChange` handlers
- Server-side errors (e.g. duplicate name or email) are extracted from DRF's
  field error format (`{ field: ['message'] }`) and shown in the modal

`App.jsx` updated to import and use the real `Surgeons` component.

---

## Step 6 — Operation Types page

**Status: Complete**

**New `src/components/Modal.jsx`** — reusable modal shell extracted here
(rather than in Step 5) to avoid repeating the structure a second time.
`Surgeons.jsx` was updated to use it as well. Accepts `title`, `onClose`,
`onSubmit`, `isPending`, and `children` props.

**`src/pages/OperationTypes.jsx`** — two sections on one page:
- **Operation Types** — `useQuery(['operation-types'])` → table with full
  CRUD for admins
- **Steps** — `useQuery(['steps'])` → table with full CRUD for admins; a
  note explains steps are global (not per-operation-type) and are suggested
  automatically from historical data

Both sections share a `ReferenceTable` sub-component defined in the same
file, which accepts column definitions, row data, and callback props. Avoids
duplicating the table + empty-state + admin-action-column structure twice.

Two independent modal states (`opModal` / `stepModal`) so both can coexist
without interfering. An `errorMessage` helper extracts DRF field-error
objects into a display string — used by both mutation `onError` handlers.

`App.jsx` updated to import and use the real `OperationTypes` component.

---

## Step 7 — Dashboard

**Status: Complete**

**Backend changes:**
- `OperationInstanceSerializer` — added `operation_type_name` and
  `surgeon_name` as read-only `CharField(source=...)` fields. The
  `OperationInstanceViewSet` queryset already uses `select_related('operation_type',
  'surgeon')` so these resolve without extra queries.
- `OperationInstanceDetailSerializer` — same two fields added for consistency
  (stats page will use them).
- `test_serializers.py` — two `test_expected_fields` assertions updated to
  include the new fields.

**`src/pages/Dashboard.jsx`:**
- Two parallel `useQuery` calls: one for `?complete=false` (active), one for
  `?complete=true` (completed). Separate query keys so React Query caches and
  invalidates them independently.
- Active operations rendered as Bootstrap cards via an `ActiveCard` sub-
  component. Cards branch on `in_room_time`:
  - Null → "Setup Steps →" button linking to `/operations/:id/ocs1`
  - Set → "Resume Timing →" button linking to `/operations/:id/ocs2`
- Completed operations rendered in a compact table. The Surgeon column appears
  only when `user.is_staff` is true (admins see all surgeons; surgeons only see
  their own, so the column would just repeat their name).
- `formatDuration(seconds)` helper renders `elapsed_time` as `"Xm Ys"` (or
  just `"Xm"` when seconds are zero) rather than a raw integer.
- Each completed row has a "View Stats" link to `/operations/:id/stats`.
- `completedData.count` (the paginated total, not just the page length) drives
  the section heading so "Completed (47)" is accurate even if only 25 rows fit
  on the first page.

`App.jsx` updated to import and use the real `Dashboard` component.

---

## Step 8 — Begin Operation form

**Status: Complete**

**Backend change:** `MeView` updated to include `surgeon_id` in its response —
the ID of the `Surgeon` record linked to the current user, or `null` if none.
Wrapped in a `try/except` because Django raises `RelatedObjectDoesNotExist`
when a User has no reverse OneToOne Surgeon.

**`src/pages/BeginOperation.jsx`:**
- `form` state initialised with `date: todayISO()` (today in YYYY-MM-DD),
  `operation_type: ''`, `detail: ''`, and `surgeon` pre-set to
  `user.surgeon_id` for non-admin users (or `''` for admins who will pick
  from the dropdown)
- Operation types fetched via `useQuery(['operation-types'])` — reuses the
  cache already populated by the Operation Types page if visited previously
- Surgeon list fetched only for admin users (`enabled: isAdmin`) — avoids an
  unnecessary request for the common case
- Non-admin users: surgeon field is a hidden `<input type="hidden">` so the
  value is submitted with the form without being visible or editable
- Admin users: surgeon field is a `<select>` dropdown populated from the
  surgeons list
- Guard: if a non-admin has no `surgeon_id` (account not linked to a surgeon
  record), an explanatory warning is shown instead of the form
- On success: `createMutation.onSuccess` receives the created
  `OperationInstance` and navigates to `/operations/:id/ocs1`
- Cancel button navigates back to `/` (Dashboard)

`App.jsx` updated to import and use the real `BeginOperation` component.

---

## Step 9 — OCS1: step setup

**Status: Complete**

**Backend change:** `StepInstanceSerializer` — added `'operation_instance'` to
`fields`. This is required because `POST /api/v1/step-instances/` must know
which operation the step belongs to. The field was missing from the serializer
because the original design only used `StepInstance` objects nested inside an
`OperationInstance` (read-only), never as standalone creates.
`test_serializers.py` `TestStepInstanceSerializer.test_expected_fields` updated
to include `'operation_instance'`.

**`src/pages/OCS1.jsx`:**

Four queries on mount (all fire in parallel):
1. `GET /operation-instances/:id/` — operation detail for the info header and
   guards (`in_room_time`, `complete`)
2. `GET /step-instances/?operation_instance=:id` — existing step instances in
   order, from the paginated list endpoint
3. `GET /operation-instances/:id/suggested-steps/` — flat array of `{id, title}`
   Step objects based on history (not paginated; returns an empty array for brand-
   new operation types with no history)
4. `GET /steps/?page_size=100` — full step list for the manual "Add" dropdown

Guards:
- `operation.complete` → `useEffect` redirects to `/operations/:id/stats`
- `operation.in_room_time` is set → shows an info alert with a link to OCS2
  (prevents accidentally resetting an already-in-progress operation's timing)

**Suggested steps panel:** shown only when the current step list is empty AND
there is at least one suggestion. Shows the steps numbered in suggested order,
with a per-item `+ Add` button and a bulk `+ Add All` button at the top. When
the list is not empty the panel is hidden — the user is assumed to have already
accepted or rejected the suggestions.

**Manual step picker:** a `<select>` + `Add` button, always visible. Adds a
step instance at `order = instances.length` (current list length). Resets the
dropdown to `"— add a step —"` after each add.

**"Enter Room" button:** disabled until at least one step is in the list.
Records `nowTimeStr()` (current local time as `HH:MM:SS`) via `PATCH
/operation-instances/:id/`. On success: invalidates all
`['operation-instances']` queries (Dashboard is now stale) and navigates to
OCS2.

`App.jsx` updated to import and use the real `OCS1` component.

---

## Step 10 — OCS2: live timing

**Status: Complete**

**`src/pages/OCS2.jsx`:**

Two queries on mount:
1. `['operation-instance', id]` → `GET /operation-instances/:id/` — operation
   info for the header and guards
2. `['step-instances', id]` → `GET /step-instances/?operation_instance=:id`
   — ordered step list

**Running clock:** `elapsed` state (integer seconds) updated by `setInterval`
inside a `useEffect`. The effect depends on `operation.in_room_time`; it
records `base = timeStrToSeconds(in_room_time)` and fires
`setElapsed(currentSeconds() - base)` every second. The `currentSeconds()`
function reads `new Date()` at call time — it is not reactive. Every `setElapsed`
call triggers a re-render, and every re-render calls `stepElapsed(si)` which
also calls `currentSeconds()`, so the active step's live column updates for
free alongside the main clock.

**`stepElapsed(si)` helper:** returns elapsed seconds for a step using whichever
data is available:
- `si.elapsed_time !== null` → use the API value (set by `complete_operation`)
- Both `start_time` and `end_time` set, `elapsed_time` null → compute locally
  (`end_time - start_time`)
- Only `start_time` set → compute live (`currentSeconds() - start_time`)
- Neither set → `null` (displayed as `—`)

**Step table row states:**
- Neither time: "Now" button in Start column; `—` in End and Elapsed
- Active (start set, no end): highlighted `table-primary`; start time shown;
  "Now" button in End column; live elapsed in Elapsed
- Done (both set): both times shown; computed elapsed shown; no highlight

**Mutations:**
- `startMutation(siId)` → `PATCH /step-instances/:id/ { start_time: now }`
- `endMutation(siId)` → `PATCH /step-instances/:id/ { end_time: now }`
- Both invalidate `['step-instances', id]` on success
- `completeMutation()` → `POST /operation-instances/:id/complete/`; on success
  invalidates all `['operation-instances']` queries (Dashboard stale) and
  navigates to stats

**"Complete Operation" button:** disabled until `instances.every(si => si.end_time)`
is true. Shows a `title` tooltip explaining the requirement when disabled. Shows
a DRF error alert if `complete_operation()` raises a `ValueError` (e.g. missing
end times or non-monotone times).

Guards (same pattern as OCS1):
- `operation.complete` → `useEffect` redirects to stats
- `!operation.in_room_time` → warning alert with link back to OCS1

`App.jsx` updated to import and use the real `OCS2` component.

---

## Step 11 — Post-op stats page

**Status: Complete**

**`src/pages/PostOpStats.jsx`:**

One query: `['operation-instance', id]` → `GET /operation-instances/:id/`
using the detail serializer, which already includes nested `steps[]` with
`dist_from_average` computed. No second fetch needed.

**Cache seeding in OCS2:** `completeMutation.onSuccess` was updated to call
`queryClient.setQueryData(['operation-instance', id], res.data)` using the
response body from `POST /complete/` (which returns the full detail). This
means when `PostOpStats` mounts immediately after navigation, React Query finds
fresh data in the cache and does not trigger a network request or show a
loading state.

**`rowClass(dist)`:** returns `'table-success'`, `'table-warning'`,
`'table-danger'`, or `''` based on `|dist_from_average|`. The empty string
is used for null (no history) — no Bootstrap class applied means the row
renders with the default background.

**`formatDist(dist)`:** returns `'+12.3%'` or `'-5.1%'` (always one decimal
place with an explicit sign for positive values). Returns `null` for null dist,
which is checked in the JSX to show `<span className="text-muted">—</span>`
instead.

**"Download CSV" button:** a plain `<a href="/api/v1/operation-instances/:id/export-csv/">`
tag. Browser requests carry httpOnly cookies automatically, so no Axios
involvement is needed. The Vite dev proxy and nginx production proxy both
forward `/api/` to the backend, so the URL resolves correctly in both
environments.

**Color legend:** a small `<p>` below the table with Bootstrap badge colors
explaining the thresholds. Badges use a single space as content to render as
colored squares.

**"Not complete" warning:** a yellow alert shown when `operation.complete` is
false (navigated directly to `/stats` before completing, or stale cache). The
page is still usable — it shows whatever data is available.

`App.jsx` updated to import and use the real `PostOpStats` component.
`Placeholder` component is now unused and removed.

---

## Step 12 — Frontend Dockerfile (multi-stage) + nginx + docker-compose.yml

**Status: Complete**

**`frontend/.dockerignore`** — created to exclude `node_modules/` and `dist/`
from the Docker build context. Without this, Docker would send the entire
`node_modules` directory (potentially hundreds of MB) to the daemon before
the build even starts, negating the cache-optimized layer strategy.

**`frontend/Dockerfile`** (multi-stage):
```dockerfile
# Stage 1: build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./    # ← copied first so npm ci is cached unless deps change
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```
Uses `npm ci` (clean install from `package-lock.json`) rather than `npm install`
for reproducible builds — same package versions every time, no version drift.

**`frontend/nginx.conf`**:
- `location /api/` — `proxy_pass http://backend:8000` with standard proxy
  headers (`Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`)
- `location /admin/` — same proxy to backend
- `location /` — `try_files $uri $uri/ /index.html` for the SPA fallback

**`docker-compose.yml`** changes:
- Added `frontend` service: `build: ./frontend`, `ports: ["80:80"]`,
  `depends_on: [backend]`, `restart: unless-stopped`
- Removed `ports: 8000:8000` from the `backend` service — all browser traffic
  now flows through nginx. The backend is still reachable at
  `http://backend:8000` from within the Docker network.

---

## Step 13 — Docs: milestones.md + milestone-5/ directory

**Status: Complete**

- `documentation/milestones.md` — M5 status updated from Planned to Complete;
  key outcomes rewritten to reflect what was actually built (cookie auth,
  AuthContext, React Query, per-page decisions, Docker details)
- `documentation/milestone-5/running-and-testing.md` — created with:
  - Option A (local dev): Django runserver + Vite dev server; `DATABASE_URL`
    must use `@localhost:`; nvm prefix requirement noted
  - Option B (Docker Compose): `DATABASE_URL` must use `@db:`; first-run
    superuser creation via `docker compose exec`
  - Test data setup instructions (surgeon, operation type, steps, user link)
  - 10-section manual test checklist covering every page and auth flow
  - Summary table for quick pass/fail verification
