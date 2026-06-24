# Milestone 5 — Frontend Design Decisions

This document explains the technology choices made for the React frontend and
how they fit together. It is written for someone who understands the Django
backend but is less familiar with the modern React ecosystem.

---

## Build tool: Vite

Vite is the build tool that compiles, bundles, and serves the React application.

In development, Vite runs a fast dev server (port 5173 by default) with
Hot Module Replacement (HMR) — when you save a file, only the changed module
is swapped into the running page without a full browser reload. This makes the
edit-and-see feedback loop nearly instant.

For production, Vite bundles everything into static files (`dist/`) that nginx
serves directly. The output is a small set of HTML, CSS, and JavaScript files
that any static file server can host.

**Why Vite over Create React App (CRA)?** CRA was the dominant scaffolding
tool for several years but is now unmaintained. Vite is its successor in
practice: faster startup, faster builds, and actively developed.

### The dev proxy

`vite.config.js` includes a proxy rule:

```js
server: {
  proxy: {
    '/api': 'http://localhost:8000',
  }
}
```

This means: when the React app running on port 5173 makes a request to
`/api/v1/surgeons/`, Vite's dev server forwards that request to Django on
port 8000 and returns the response.

From the browser's point of view, all requests go to port 5173 — a single
origin. This is important because browsers enforce the Same-Origin Policy:
JavaScript is only allowed to read responses from the same origin that served
the page (same protocol + hostname + port). Without the proxy, every API call
would be a cross-origin request and would fail unless the Django server
explicitly allows it with CORS headers.

The proxy is a dev-only shortcut. In production (Docker Compose), nginx plays
the same role — it receives all traffic on port 80 and routes `/api/` requests
to the backend container.

---

## UI framework: React

React is a JavaScript library for building user interfaces out of components.
A component is a function that takes inputs (called "props") and returns a
description of what should appear on screen (JSX). React handles updating the
DOM when that description changes.

Timer 2.0's UI is a Single-Page Application (SPA): the browser loads one HTML
file and one JavaScript bundle, then React renders everything inside it. Page
navigations are handled by JavaScript — the browser never does a full reload.
This is what allows the OCS2 live clock to keep ticking while the user
interacts with the step buttons.

**Why a SPA over Django templates?** Django templates require a round trip to
the server for every interaction. A timer that needs to update a live elapsed
clock every second, or record a step timestamp the moment a button is clicked,
needs client-side logic that templates cannot provide cleanly.

---

## Routing: React Router

React Router maps URL paths to React components. When the URL is
`/operations/42/ocs2`, React Router renders the OCS2 page component with `42`
available as a parameter. Navigating to a new URL (via a Link or the
`useNavigate` hook) changes the address bar and swaps the rendered component
— without a browser reload.

The `BrowserRouter` variant uses real URL paths (`/login`, `/dashboard`) rather
than hash-based paths (`/#/login`). This requires the server to serve the same
`index.html` for every path, which is why nginx is configured with the
`try_files` SPA fallback — if a user navigates directly to
`http://localhost/operations/42/ocs2`, nginx hands back `index.html` and React
Router takes over from there.

---

## Data fetching: React Query (TanStack Query)

React Query manages the lifecycle of server data in a React app. Instead of
writing `useEffect` hooks that fetch data, update loading/error state, and
re-fetch on changes manually, React Query provides `useQuery` and
`useMutation` hooks that handle all of that automatically.

```js
// Without React Query — manual, verbose
const [surgeons, setSurgeons] = useState([]);
const [loading, setLoading] = useState(true);
useEffect(() => {
  client.get('/surgeons/').then(r => { setSurgeons(r.data); setLoading(false); });
}, []);

// With React Query — declarative, cached, automatic
const { data: surgeons, isLoading } = useQuery({
  queryKey: ['surgeons'],
  queryFn: () => client.get('/surgeons/').then(r => r.data),
});
```

Key behaviors React Query provides automatically:

- **Caching** — the surgeon list is fetched once and reused across components.
  If the Surgeons page is visited a second time, the cached data is shown
  instantly while a background refresh happens.
- **Invalidation** — after a mutation (create/edit/delete a surgeon), calling
  `queryClient.invalidateQueries(['surgeons'])` triggers a refetch so the UI
  reflects the new state.
- **Background refetch** — data is refreshed when the user returns to the
  browser tab after being away.
- **Error and loading states** — `isLoading`, `isError`, and `error` come for
  free without any manual state management.

---

## HTTP client: Axios

Axios is the library that makes HTTP requests from JavaScript. It is used in
preference to the browser's native `fetch` for a few reasons:

- **Request/response interceptors** — Axios allows middleware-style
  interception of every request and response. Timer 2.0 uses a response
  interceptor to catch 401 errors, automatically attempt a token refresh, and
  retry the original request — all transparently, without any page-specific
  error handling code.
- **`withCredentials: true`** — this single config flag tells the browser to
  include cookies on every request, which is required for the httpOnly cookie
  auth scheme.
- **Automatic JSON handling** — Axios serializes and deserializes JSON
  automatically; `fetch` requires manual `.json()` calls.

The axios instance is created once in `src/api/client.js` and imported
everywhere, so the base URL and all interceptors are configured in one place.

---

## Styling: Bootstrap 5

Bootstrap is a CSS framework that provides pre-built component styles via
class names. Adding `class="btn btn-primary"` to a button makes it look like
a styled primary button without writing any CSS.

Bootstrap is used here as plain CSS (imported from the npm package) rather
than via React-Bootstrap (component wrappers). This keeps things simple: the
components are standard HTML elements with Bootstrap classes on them, which is
easy to read and easy to inspect in the browser.

Relevant Bootstrap utilities used in this milestone:
- **Grid** (`container`, `row`, `col-*`) — page layout
- **Cards** — Dashboard operation cards, Login form
- **Table** — Step Instance data tables, post-op stats
- **Contextual table colors** (`table-success`, `table-warning`, `table-danger`) — dist_from_average color coding
- **Modal** — Create/Edit forms for Surgeons and Operation Types
- **Alerts** — login errors, form validation messages
- **Navbar** — the app shell header

---

## Authentication: httpOnly cookies

JWT access and refresh tokens are stored in `HttpOnly` browser cookies rather
than in JavaScript-accessible storage (localStorage or React state).

**Why httpOnly cookies?**

A cookie marked `HttpOnly` cannot be read or modified by JavaScript — only the
browser can access it, and it is sent automatically with every request to the
same origin. This means that even if an attacker injects malicious JavaScript
into the page (XSS), they cannot steal the token. Tokens in localStorage have
no such protection.

**How the flow works:**

1. User logs in → Django sets two httpOnly cookies: `access` and `refresh`.
2. Every subsequent API request from Axios (with `withCredentials: true`)
   includes those cookies automatically — no code needed per request.
3. When the access token expires (15 minutes), the backend returns 401. The
   Axios interceptor catches this, POSTs to `/auth/refresh/` (the browser
   sends the refresh cookie), Django returns a new access cookie, and the
   original request is retried.
4. On logout, Django calls `delete_cookie()` for both cookies.

**The `/me/` endpoint**

Because JavaScript cannot read the httpOnly cookie, it cannot decode the JWT
to know who the user is. `GET /api/v1/auth/me/` solves this: it returns
`{id, username, is_staff}` for the authenticated user. AuthContext calls this
once on app startup to establish login state.

**`SameSite=Lax`**

The cookies are set with `SameSite=Lax`, which tells the browser to send them
on same-origin requests and on top-level navigations from external sites, but
not on cross-site sub-resource requests. This prevents CSRF attacks — a
malicious site cannot trick a logged-in user's browser into making API calls
that carry their cookies.

---

## Docker: multi-stage frontend build

The frontend `Dockerfile` uses a two-stage build to keep the final image small:

**Stage 1 (build)** uses a Node.js image to run `npm run build`, producing the
static `dist/` directory. Node and all npm packages are only needed at build
time and are discarded after this stage.

**Stage 2 (serve)** uses a minimal nginx image and copies only the `dist/`
files from stage 1. The resulting image is ~25 MB (vs ~300 MB if Node were
included) and has no npm tooling or source code in it.

nginx serves the static files and proxies `/api/` and `/admin/` to the backend
container. This is how the SPA reaches the Django API in production without
any CORS configuration.

---

## Summary: how the pieces fit together

```
Browser
  │
  ├── GET /          → nginx → serve index.html + JS bundle
  ├── GET /api/v1/   → nginx → proxy to backend:8000
  └── GET /admin/    → nginx → proxy to backend:8000

React (in browser)
  │
  ├── React Router   → maps URL to page component
  ├── React Query    → fetches, caches, and re-syncs server data
  ├── Axios          → makes HTTP requests; intercepts 401s for token refresh
  └── AuthContext    → tracks login state; exposes login/logout to all pages

Django (backend)
  │
  ├── /api/v1/auth/  → login (set cookies), refresh (renew access cookie),
  │                     logout (clear cookies), me (return user info)
  └── /api/v1/*      → all other endpoints; auth enforced via JWT cookie
```
