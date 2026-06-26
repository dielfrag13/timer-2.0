# Grafana User Guide — Timer 2.0

This guide explains how to access Grafana after a successful kind cluster
deployment, what the pre-built dashboards show, how to read them, and how
to write your own queries.

---

## Accessing Grafana

Grafana runs inside the cluster and is not exposed through the Ingress (the
Ingress routes traffic to the timer application, not Grafana). You access it
by forwarding the Grafana pod's port to your local machine:

```bash
kubectl port-forward svc/grafana 3000:80 -n logging
```

Leave this command running in a terminal. Open `http://localhost:3000` in your
browser.

**Default credentials:**
- Username: `admin`
- Password: `admin`

Grafana will prompt you to change the password on first login. You can skip
this for local development, but you should change it if the cluster is
accessible to others.

---

## What you should see after a successful deployment

When Grafana loads for the first time after the cluster is set up:

1. **Left sidebar → Dashboards** — you should see a folder named
   **"Timer 2.0"** containing two dashboards:
   - Timer 2.0 — Audit Events
   - Timer 2.0 — API Requests

   If the folder is missing, the Grafana sidecar has not yet loaded the
   dashboard ConfigMap. Wait 30 seconds and refresh, or check:
   ```bash
   kubectl get configmap timer-dashboards -n logging
   kubectl logs -l app.kubernetes.io/name=grafana -n logging -c grafana-sc-dashboard
   ```

2. **Left sidebar → Connections → Data sources** — you should see **"Loki"**
   listed as the default datasource (marked with a star). If it is missing,
   the datasource provisioning failed; check the Grafana pod logs:
   ```bash
   kubectl logs -l app.kubernetes.io/name=grafana -n logging
   ```

3. **Loki datasource test** — click the Loki datasource → "Save & test". You
   should see "Data source connected and labels found." If it shows a connection
   error, Loki may still be starting. Wait for:
   ```bash
   kubectl get pods -n logging
   # loki-0 should be Running and 1/1 Ready
   ```

---

## Dashboard: Timer 2.0 — Audit Events

**Purpose:** This dashboard tracks who did what and when — logins, logouts,
and operation lifecycle events. It answers questions like: "How many operations
were completed today?" and "Are there any unusual login failure spikes?"

**Time range:** Defaults to the last 6 hours. Use the time picker in the
top-right corner to zoom out to "Last 7 days" or set a custom range.

**Auto-refresh:** Every 30 seconds by default. Change in the top-right dropdown.

### Panels

**Total Audit Events** (blue stat, top-left)
The count of all events in `timer.audit` within the selected time range. This
includes logins, logouts, and every operation lifecycle event. A healthy
day of surgery should show a steady count here.

**Login Failures** (red stat, top-center)
The count of `login_failure` events. This panel turns red if the value is
non-zero. A spike here could indicate a user repeatedly mistyping their
password or, in a production system, a brute-force attempt. Click the panel
title → "Explore" to drill into the raw log lines and see which username
and IP is triggering failures.

**Operations Completed** (green stat, top-right)
The count of `operation_complete` events — each one represents a full surgical
procedure that was timed to completion. Comparing this to total audit events
gives a rough sense of how busy the system was.

**Audit Events Over Time** (bar chart)
Shows four time series in 5-minute buckets:
- **logins** — `login_success` events
- **operations started** — `operation_create` events
- **operations completed** — `operation_complete` events
- **login failures** — `login_failure` events

You should see operations started and completed in rough pairs, with logins
appearing before them as surgeons sign in. If completed is consistently lower
than started, it may indicate operations being abandoned mid-timing.

**All Audit Events** (log panel at bottom)
A scrollable, most-recent-first view of every audit event. Each line can be
expanded by clicking it — you'll see the full JSON payload including the
surgeon's username, user ID, IP address, and operation details.

Use the search bar above the log panel to filter by text. For example:
- Type `login_failure` to see only failed logins
- Type `operation_complete` to see only completed operations
- Type a specific username to trace one person's activity

The "Pretty print" option (enabled by default) formats the JSON so it's easy
to read. Toggle it off if you want to copy raw log lines.

---

## Dashboard: Timer 2.0 — API Requests

**Purpose:** This dashboard tracks the health and performance of the REST API
— request volume, error rates, and response times. It answers questions like:
"Is the API slow right now?" and "What requests are returning errors?"

**Time range:** Defaults to the last 1 hour. Zoom out for trend analysis.

### Panels

**Total Requests** (blue stat, top-left)
All requests logged by `timer.api` in the selected time range. Every HTTP
request to the backend — login, data fetches, mutations — is counted here.

**5xx Errors** (red stat, top-center)
Requests where Django returned a 500-level response. These are server-side
failures — unhandled exceptions, database errors, configuration problems. In
a healthy system this should always be zero. If it's non-zero, check the "4xx
/ 5xx Request Logs" panel at the bottom to see which endpoints are failing,
then check the backend pod logs:
```bash
kubectl logs -l app=backend -n timer --since=15m
```

**4xx Warnings** (orange stat, top-right)
Requests where Django returned a 400-level response. These are client-side
errors — bad input, auth failures (401), permission denied (403), not found
(404). A moderate number of 401s is normal (expired tokens triggering a refresh
cycle). A spike in 404s or 400s may indicate a frontend bug or API mismatch.

**Request Rate (per second, 1-min window)** (left time series)
Shows three overlapping lines:
- **all requests** — total request rate
- **5xx errors** — error rate
- **4xx warnings** — warning rate

A healthy system shows a flat "all requests" line during surgery hours and
effectively-zero error/warning lines. Spikes in the error line warrant
investigation. If you see the error line rise while the all-requests line
stays flat, a specific endpoint is consistently failing. If both rise together,
overall traffic increased suddenly.

**Response Time (1-min window)** (right time series)
Shows two lines:
- **avg response time** — average across all requests in each 1-minute window
- **p95 response time** — the 95th percentile (95% of requests are faster than this)

The p95 line is the more important one — averages can hide occasional slow
requests. A typical well-functioning Django + Postgres stack should show:
- Average under 50ms for read endpoints
- Average under 200ms for mutation endpoints (create operation, complete operation)
- p95 under 500ms

If p95 climbs above 1000ms consistently, investigate the database (slow queries,
lock contention) or backend pod resources (HPA scaling up is the expected
response to CPU pressure).

The response time panel uses LogQL metric extraction:
`avg_over_time({...} | json | unwrap duration_ms [1m])` — this parses the
`duration_ms` field from each JSON log line and computes the metric. It only
works because the `RequestLoggingMiddleware` logs `duration_ms` on every request.

**4xx / 5xx Request Logs** (log panel at bottom)
Shows only WARNING (4xx) and ERROR (5xx) log lines — the noisy successful
requests are filtered out. Expand any line to see:
- `method` — GET / POST / PATCH / DELETE
- `path` — which endpoint (`/api/v1/operation-instances/`, etc.)
- `status` — exact HTTP status code (400, 401, 403, 404, 500, etc.)
- `duration_ms` — how long the failing request took

This is the fastest way to diagnose a specific error. If the "5xx Errors" stat
is non-zero, scroll here first.

---

## Writing your own queries (LogQL basics)

Grafana's Explore view (left sidebar → compass icon) lets you run ad-hoc
LogQL queries. Here are common patterns:

### Filter by log stream

```logql
{namespace="timer", logger="timer.audit"}
```
Every field in `{}` is a label filter. Labels were indexed by Promtail and
are fast to query. Only use labels here — putting high-cardinality values like
user IDs in label filters won't work because they weren't promoted to labels.

### Filter by text within the log line

```logql
{namespace="timer", logger="timer.audit"} |= "login_failure"
```
`|=` is a line filter (substring match). Use `!=` to exclude lines, `|~` for
regex match, `!~` for regex exclusion.

### Parse JSON fields and filter by value

```logql
{namespace="timer", logger="timer.api"} | json | status >= 500
```
`| json` parses the JSON log line and makes all fields available as filter
targets. `status >= 500` filters to only 5xx responses.

### Count events over time

```logql
count_over_time({namespace="timer", logger="timer.audit"} |= "login_failure" [5m])
```
Returns a time series: count of login failures in each 5-minute window.

### Extract a numeric metric

```logql
avg_over_time({namespace="timer", logger="timer.api"} | json | unwrap duration_ms [1m])
```
`unwrap duration_ms` extracts the numeric `duration_ms` field from each JSON
log line so it can be used in aggregation functions (`avg_over_time`,
`max_over_time`, `quantile_over_time`, etc.).

### Trace a specific user's activity

```logql
{namespace="timer", logger="timer.audit"} | json | username = "jsmith"
```
Parses JSON and filters to log lines where `username` equals `jsmith`. Use
this to audit a specific user's login history and operation activity.

---

## What to check after each deployment

After deploying a new version or making changes:

1. Open the **API Requests** dashboard. Set the time range to "Last 15 minutes."
2. Verify the request rate is non-zero (traffic is flowing).
3. Verify the "5xx Errors" stat is zero.
4. Check the p95 response time is not elevated compared to before the deployment.
5. Open the **Audit Events** dashboard. Confirm logins and operations are being
   recorded (if there is activity on the system).

If anything looks wrong, drill into the log panels to find the specific
requests or events causing the anomaly.
