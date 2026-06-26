# Milestone 6 — Implementation Notes

Detailed notes on non-obvious decisions made during each step. The
`design-decisions.md` file explains *what* each technology is; these notes
explain *why specific choices were made* within each step of the implementation.

---

## Step 2 — Namespace, ConfigMap, Secret

### Why a dedicated namespace (`timer`)?

Kubernetes clusters often run many unrelated workloads. A namespace gives
timer-2.0 its own isolated corner: resource quotas, RBAC rules, and network
policies can all be scoped to `timer` without affecting anything else. Within
the namespace, services discover each other by short name (`backend`, `postgres`)
rather than the fully-qualified `backend.timer.svc.cluster.local`. This is the
same reason Docker Compose services discover each other by service name — it's
the same DNS shortcut, just implemented by K8s instead of Docker.

### Why split config across ConfigMap and Secret?

The split is about sensitivity, not convenience:

- **ConfigMap** holds values that are safe to read in plaintext: `DEBUG`,
  `LOG_LEVEL`, `ALLOWED_HOSTS`. A developer checking on a running pod with
  `kubectl describe configmap` sees these immediately — that's fine.
- **Secret** holds values that would be catastrophic to expose: `SECRET_KEY`
  (forging Django sessions if leaked), `DATABASE_URL` (direct database access),
  and the Postgres credentials. Secrets are base64-encoded in etcd and can be
  encrypted at rest; access can be restricted via RBAC independently of ConfigMap
  access.

Base64 is not encryption. `secret.yaml` must never be committed to git — it
is listed in `.gitignore` for exactly this reason. In a real production cluster,
you'd use an external secret manager (AWS Secrets Manager, HashiCorp Vault)
rather than a plain Secret manifest. For this project, the gitignored file is
the right tradeoff.

### Why must `ALLOWED_HOSTS` match the Ingress hostname?

Django's `ALLOWED_HOSTS` setting is a security check against HTTP Host header
spoofing. Every incoming request's `Host` header is checked against this list;
if it doesn't match, Django returns 400 Bad Request before processing the
request at all. When nginx-ingress forwards a request to the backend, it
preserves the original `Host` header (e.g., `timer.local`). If `ALLOWED_HOSTS`
in the ConfigMap doesn't include `timer.local`, every request fails with 400
— the app appears completely broken. The value must be updated to match the
real domain when deploying to production.

### Why `SECURE_PROXY_SSL_HEADER`?

nginx-ingress terminates the TLS connection from the browser. The connection
nginx-ingress makes to the backend pod is plain HTTP inside the cluster.
Without `SECURE_PROXY_SSL_HEADER`, Django sees only the plain HTTP connection
and `request.is_secure()` returns `False`. This breaks two things:

1. `SESSION_COOKIE_SECURE = not DEBUG` — Django sets the Secure flag on cookies
   only when `request.is_secure()` is True. Without this, cookies are sent over
   HTTP too, defeating the purpose of HTTPS.
2. `CSRF_COOKIE_SECURE` — same issue with the CSRF cookie.

`SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` tells Django:
"if the `X-Forwarded-Proto` header says `https`, trust it and treat this
request as HTTPS." nginx-ingress sets that header on every forwarded request.
This header is only trustworthy because nginx-ingress strips any
`X-Forwarded-Proto` header that a client sends directly — an attacker cannot
forge it.

### Why is `secret.yaml` gitignored but `secret.example.yaml` committed?

`secret.yaml` contains real credentials. If committed, every person with repo
access — and every system that clones the repo (CI, a compromised machine) —
has the database password and Django secret key. `secret.example.yaml` is a
template with placeholder values: it documents the required fields without
exposing real values. The workflow is: copy `secret.example.yaml` to
`secret.yaml`, fill in real values, never commit `secret.yaml`.

---

## Step 3 — PostgreSQL StatefulSet + Service

### Why StatefulSet instead of Deployment?

Deployments are designed for stateless workloads: pods are interchangeable,
can be replaced in any order, and have no persistent identity. Postgres is
stateful: it needs to write to the same data directory across restarts, and
it needs a stable network identity so clients can reconnect after a pod restart.

StatefulSet provides two things a Deployment doesn't:
1. **Stable pod names** — `postgres-0` always has the DNS name
   `postgres-0.postgres.timer.svc.cluster.local`. A Deployment's pods get
   random suffixes that change on every restart.
2. **Persistent storage per pod** — `volumeClaimTemplates` creates a named PVC
   (`postgres-data-postgres-0`) that is reattached to the pod on restart rather
   than deleted. With a Deployment, a pod's volume is ephemeral by default —
   all data would be lost on every pod replacement.

### Why `PGDATA=/var/lib/postgresql/data/pgdata`?

When Kubernetes mounts a PVC (Persistent Volume Claim) at a path, the mounted
directory is the root of the underlying volume. Most Linux filesystems create a
`lost+found` directory at the root of a new volume. Postgres checks the data
directory on startup and refuses to initialize if it contains any files —
including `lost+found`. Setting `PGDATA` to a subdirectory (`/pgdata`) means
Postgres initializes into an empty subdirectory rather than the root of the
mount, sidestepping this issue entirely. The `lost+found` directory stays at
the volume root and is ignored.

### Why `pg_isready` for probes instead of a TCP check?

Postgres has a two-phase startup:
1. The process starts and binds to port 5432.
2. It finishes initializing and begins accepting connections.

A TCP probe (checking that port 5432 is open) passes after phase 1. But
`pg_isready` waits until phase 2 — it actually attempts a connection and
checks the response code. If the readiness probe used a TCP check, backend
pods could attempt migrations against a Postgres that is listening but not
yet ready to respond, causing failures that `backoffLimit` then has to retry.

### Why does the database need a PVC if Docker Compose used a named volume?

Same reason, different implementation. Docker Compose's `postgres_data:` named
volume persists across `docker compose down` (but not `docker compose down -v`).
A Kubernetes PVC persists across pod restarts and replacements until explicitly
deleted with `kubectl delete pvc`. In both cases, the data lives outside the
container so it survives the container's lifecycle.

### Why is the Service named `postgres`?

`DATABASE_URL` in `secret.example.yaml` uses `postgres` as the hostname:
`postgres://timer:password@postgres:5432/timer`. Within the `timer` namespace,
Kubernetes DNS resolves `postgres` to the ClusterIP of this Service, which
then routes to the `postgres-0` pod. If the Service were named anything else,
`DATABASE_URL` would need to change to match.

---

## Step 4 — Migration Job

### Why a Job instead of running `migrate` in the Deployment?

A Kubernetes Job runs a container to completion and stops. A Deployment keeps
containers running indefinitely and restarts them if they exit. Running
`migrate` in the Deployment would mean every pod restart triggers a migration
attempt — which is harmless but noisy, and creates a race condition if two
pods start simultaneously on a fresh cluster with no migrations applied yet.
Running migrations as a separate Job, with the apply script waiting for the
Job to complete before starting the Deployment, ensures migrations are done
exactly once before any backend pods try to serve traffic.

### Why override CMD to `true` instead of writing a new command?

`entrypoint.sh` already does exactly what the migration Job needs:
1. Parse Postgres connection details from `DATABASE_URL`
2. Wait for Postgres to be ready with `pg_isready`
3. Run `python manage.py migrate`
4. Call `exec "$@"` (the CMD)

By overriding just the CMD to `true` (`args: ["true"]` in K8s), the
entrypoint runs its three useful steps and then calls `exec true`, which exits
0. The Job sees a clean exit and marks itself Complete. Writing a separate
entrypoint script or command would duplicate the Postgres-wait logic.

In Kubernetes, `args` overrides the Docker `CMD` while leaving the `ENTRYPOINT`
intact. `command` would override the entrypoint itself. Using `args` is the
right lever here.

### Why `backoffLimit: 3`?

Even with the StatefulSet readiness probe ensuring the Postgres Service doesn't
route traffic until Postgres is ready, there is a narrow window on a completely
fresh cluster where the Job pod starts, the `pg_isready` loop in the entrypoint
passes, but Postgres finishes initializing its data directory between the probe
and the first migration SQL statement. `backoffLimit: 3` means the Job retries
up to 3 times before being marked Failed, giving Postgres time to fully
initialize on first boot.

### Why `ttlSecondsAfterFinished: 300`?

A completed Job leaves its pod in `Completed` status indefinitely unless
explicitly cleaned up. Over many deployments, old completed Jobs accumulate and
clutter `kubectl get pods`. `ttlSecondsAfterFinished: 300` tells Kubernetes to
delete the Job and its pod 5 minutes after completion. Five minutes is long
enough to run `kubectl logs job/backend-migrate` to verify migrations ran
correctly, but short enough that it doesn't accumulate.

### Why must the migration Job complete before the Deployment starts?

If the backend Deployment starts before migrations run, gunicorn starts and
begins serving requests. The first request that touches the database (any API
call) will fail because the tables don't exist yet. Django's ORM does not
lazily skip missing tables — it raises an exception. The `apply.sh` script
(Step 10) uses `kubectl wait --for=condition=complete job/backend-migrate`
to block until the Job succeeds before applying the backend Deployment.

---

## Step 5 — Backend Deployment, Service, HPA

### Why 2 replicas minimum?

With 1 replica, a rolling update briefly takes the only pod offline while the
replacement starts. With 2 replicas, Kubernetes replaces one pod at a time —
the remaining pod continues serving traffic throughout. This is the simplest
form of zero-downtime deployment. The HPA's `minReplicas: 2` enforces this
even when load is low and the HPA would otherwise scale down.

### Why `imagePullPolicy: Never`?

Docker images built locally do not exist in any remote registry. When `kind
load docker-image timer-backend:latest` is run (Step 10), the image is copied
directly into kind's internal image cache. Without `imagePullPolicy: Never`,
Kubernetes would try to pull `timer-backend:latest` from Docker Hub, fail
with `ErrImagePull`, and the pod would never start. `Never` tells Kubernetes
to use only locally available images and fail immediately (rather than
retrying) if the image is not present — which makes misconfiguration obvious.

### Why separate readiness and liveness probes?

They serve different purposes:

- **Readiness** controls whether a pod receives traffic from the Service.
  A pod that is starting up (entrypoint running, gunicorn not yet bound) should
  not receive traffic — it would return connection errors. Kubernetes removes
  unready pods from the Service's endpoint list and adds them back once the
  probe passes.
- **Liveness** controls whether a pod is restarted. A pod that was healthy but
  has since deadlocked or run out of memory should be killed and replaced.

A pod can be alive but not ready (starting up). A pod that is not alive (liveness
failing) is also not ready. They are not redundant — they gate different actions.

### Why `initialDelaySeconds: 15` for readiness and `60` for liveness?

`entrypoint.sh` runs before gunicorn starts. It parses `DATABASE_URL`, runs the
`pg_isready` loop, runs `migrate` (a no-op since the Job ran first but still
takes a round-trip), and only then starts gunicorn. Total time is typically
5–10 seconds. Setting `initialDelaySeconds: 15` on the readiness probe means
Kubernetes doesn't check until the pod has had 15 seconds to complete startup —
preventing it from immediately marking the pod unready on the first check and
triggering unnecessary load balancer changes.

The liveness probe uses 60 seconds because if the readiness probe is failing
(startup took longer than expected), the liveness probe must not restart the
pod before startup is complete. With `failureThreshold: 3` and `periodSeconds:
10`, the liveness probe would kill the pod after 3 consecutive failures. Setting
`initialDelaySeconds: 60` gives the pod a full minute before liveness checks
begin, safely covering any realistic startup duration.

### Why `autoscaling/v2` for the HPA?

`autoscaling/v1` only supports CPU-based scaling and uses a different, less
flexible spec format. `autoscaling/v2` (stable since Kubernetes 1.23, which
kind 0.24.0 provides) supports CPU, memory, and custom metrics in the same
manifest. Using v2 now means the manifest doesn't need to be rewritten if
memory-based or custom scaling is added later.

### Why does the HPA require metrics-server?

The HPA controller reads CPU utilization from the Kubernetes Metrics API
(`metrics.k8s.io`). This API is implemented by `metrics-server`, a cluster
addon that collects resource usage from kubelets and aggregates it. It is not
installed by default in kind. Without it, `kubectl get hpa` shows `<unknown>`
for current CPU utilization and the HPA never scales. `setup-kind.sh` (Step 10)
installs metrics-server via Helm before the HPA manifest is applied.

### Why is the Service named `backend`?

`frontend/nginx.conf` proxies API traffic to `http://backend:8000`. Within the
`timer` namespace, Kubernetes DNS resolves `backend` to the ClusterIP of this
Service, which load-balances across the 2–6 backend pods. This is the same
resolution that Docker Compose uses — Docker Compose resolves `backend` to the
container IP, K8s resolves it to the Service ClusterIP. The nginx image built
in M5 works in both environments without any modification.

---

## Step 6 — Frontend Deployment + Service

### Why 1 replica instead of 2?

The frontend is a stateless nginx container serving pre-built static files.
There is no shared mutable state, no database connection, and no session memory
in the process. A rolling update briefly replaces the single pod, but because
nginx starts in under a second (no migrations, no startup scripts) the readiness
probe passes almost immediately and the Service starts routing traffic again
before a user would notice. Adding a second replica for zero-downtime rolling
updates is a reasonable next step, but 1 is sufficient for a single ASC's load.

### Why no `envFrom` (no ConfigMap or Secret injection)?

The frontend container is a pre-built nginx image. `nginx.conf` is baked into
the image at build time (copied in the Dockerfile). The React app is compiled
JavaScript — all configuration is resolved at build time by Vite, not at
runtime. There are no environment variables for nginx to read. This is
fundamentally different from the backend, which reads `SECRET_KEY`,
`DATABASE_URL`, and `ALLOWED_HOSTS` at startup.

If a runtime environment variable were ever needed in the React app itself
(e.g., a feature flag), it would require either rebuilding the image or using
a different approach like injecting a `window.ENV` object via an nginx
`sub_filter` — but neither is needed here.

### Why does the existing `nginx.conf` work in Kubernetes without changes?

`nginx.conf` proxies `/api/` to `http://backend:8000`. Within the `timer`
namespace, Kubernetes DNS resolves `backend` identically to how Docker Compose
does: short service names resolve within the current network context. In Docker
Compose that context is the Compose network; in Kubernetes it is the namespace.
The same image, the same config, the same hostname — no modification required.
This was a deliberate architectural decision in M5: route all traffic (static
files and API calls) through the frontend nginx, mirroring Docker Compose
exactly so the same image works in both environments.

### Why probe `GET /` rather than a dedicated health endpoint?

The frontend nginx serves the React `index.html` at `/`. A successful `200`
response from `GET /` confirms that nginx is running, the static files are
present, and the container is healthy. There is no application logic to test
here — no database connection, no business logic — so probing the root path
is sufficient. A dedicated `/health` endpoint would require nginx configuration
changes for no meaningful gain.

The short probe delays (5s readiness, 10s liveness initial delay) reflect how
fast nginx starts: typically under 1 second, with no equivalent of the backend's
entrypoint startup work.

---

## Step 7 — cert-manager + nginx-ingress + Ingress

### Why does all traffic route to the frontend Service, not split at the Ingress?

The Ingress sends everything (`path: /`, `pathType: Prefix`) to the frontend
Service on port 80. The frontend nginx then handles routing internally:
`/api/` and `/admin/` are proxied to `backend:8000`; everything else serves
`index.html` via the SPA fallback.

An alternative would be to split at the Ingress level — send `/api/` directly
to the backend Service and `/` to the frontend. This would bypass nginx
entirely for API traffic. The reason we don't do that is consistency: the same
nginx image and the same `nginx.conf` work in Docker Compose and Kubernetes
without any modification. Splitting at the Ingress would mean API traffic flows
differently in the two environments, making debugging harder and creating
configuration drift.

### What is an IngressClass and why `ingressClassName: nginx`?

A cluster can have multiple Ingress controllers (nginx, Traefik, AWS ALB, etc.)
installed simultaneously. `ingressClassName: nginx` is how an Ingress resource
says "I want the nginx-ingress controller to handle me." Without it, the
resource would be unclassed and no controller would pick it up — the Ingress
would be silently ignored. The `nginx` IngressClass is registered automatically
when ingress-nginx is installed via Helm.

### What is a ClusterIssuer and why are there two?

A `ClusterIssuer` is a cert-manager resource that defines *how* to obtain a
TLS certificate. It is cluster-scoped (not namespace-scoped), so it can issue
certificates for any namespace. Two issuers cover the two deployment contexts:

- **`selfsigned`** — cert-manager generates and signs the certificate itself.
  No external authority is involved. The browser doesn't trust it (shows a
  warning), but HTTPS works. Correct choice for local kind development where
  there is no public domain and Let's Encrypt can't reach the cluster.
- **`letsencrypt-prod`** — cert-manager contacts the Let's Encrypt ACME server,
  which issues a browser-trusted certificate for free. Requires a real public
  domain and an internet-accessible cluster.

The Ingress's `cert-manager.io/cluster-issuer` annotation names which issuer to
use. Switching from local to production is a one-line annotation change.

### How does the ACME HTTP-01 challenge work?

Let's Encrypt verifies domain ownership by asking cert-manager to prove it
controls the domain. The flow:

1. cert-manager requests a certificate for `timer.example.com` from Let's
   Encrypt.
2. Let's Encrypt responds with a challenge token and says: "serve this token
   at `http://timer.example.com/.well-known/acme-challenge/<token>`."
3. cert-manager creates a temporary Ingress rule and a pod to serve the token
   at that path.
4. Let's Encrypt makes an HTTP request to verify the token is there.
5. Verification succeeds → Let's Encrypt issues the certificate → cert-manager
   stores it in the Secret named by `spec.tls[].secretName`.

This entire flow is automatic. Renewal (every 60 days, before the 90-day
expiry) is also automatic — cert-manager watches certificate expiry and
re-runs the challenge without any manual intervention.

### Why does the Let's Encrypt ClusterIssuer mention a staging server?

Let's Encrypt production has a rate limit of 5 duplicate certificates per
domain per week. If you're iterating on the cert-manager configuration (wrong
email, wrong solver, misconfigured Ingress), you can exhaust this limit quickly
and be blocked from issuing certificates for a week. The staging server
(`acme-staging-v02.api.letsencrypt.org`) has no rate limit and issues fake
certificates that are not browser-trusted but are otherwise identical. The
correct workflow for a new production deployment is: test with staging first,
confirm the certificate is issued and stored correctly, then switch to
production.

### How does cert-manager know which Secret to store the certificate in?

The Ingress's `spec.tls[].secretName: timer-tls` names the Secret. cert-manager
watches Ingress resources with its annotation, reads `secretName`, and creates
(or updates) that Secret with the `tls.crt` and `tls.key` fields. nginx-ingress
then reads the Secret to serve HTTPS. The Secret is created in the same
namespace as the Ingress (`timer`).

### Why does the browser warn about the self-signed certificate in kind?

Self-signed means cert-manager is both the certificate authority and the
certificate requester — there is no independent third party (like Let's Encrypt)
vouching for the certificate's legitimacy. Browsers maintain a list of trusted
root certificate authorities; cert-manager's self-signed CA is not on that
list. The browser warns because it cannot verify the identity of the server.
For local development, accepting the warning is fine — you know you're
connecting to your own kind cluster. This is a development-only tradeoff; the
`letsencrypt-prod` issuer is used for any deployment that real users access.

### How does traffic actually reach the cluster in kind?

When ingress-nginx is installed with `controller.hostPort.enabled=true` (set
in `setup-kind.sh`), the ingress-nginx pod binds directly to ports 80 and 443
on the node's network interface. In kind, the node is a Docker container with
port mappings defined in `kind-config.yaml` (Step 10): host port 80 → node
port 80, host port 443 → node port 443. The result: a browser request to
`http://timer.local:80` reaches the host machine, Docker forwards it to the
kind node container, the kind node forwards it to the ingress-nginx pod, which
routes it to the frontend Service.

Adding `timer.local` to `/etc/hosts` (`127.0.0.1 timer.local`) makes the
hostname resolve to localhost, completing the chain.

---

## Step 8 — Loki + Promtail

### Why single-binary (monolithic) deployment mode for Loki?

Loki has three deployment modes:
- **Single-binary** — all components (ingester, querier, distributor, etc.) in
  one process and one pod. Simple to configure, low resource use.
- **Simple scalable** — splits read and write paths into separate deployments
  so each can scale independently. Requires an object store (S3/GCS).
- **Microservices** — each component is its own deployment. Maximum flexibility
  at maximum operational complexity.

Single-binary is the right choice here because an ASC generates a modest volume
of logs (a few hundred lines per operation). The threshold for outgrowing single-
binary is roughly 10 GB of logs per day — far more than this application will
ever produce. Simple scalable and microservices modes also require object
storage, which adds cost and configuration complexity that isn't justified at
this scale.

### Why `auth_enabled: false`?

Loki's multi-tenancy mode requires every request to include an
`X-Scope-OrgID` header identifying the tenant. For a single-tenant deployment
(one ASC, one cluster, one Loki instance), this header adds complexity with no
benefit. Disabling auth means Promtail can push logs and Grafana can query them
with no authentication headers — appropriate for an internal cluster service
that is not exposed outside the cluster.

### Why filesystem storage instead of object storage (S3/GCS)?

Object storage (S3, GCS, MinIO) is the recommended backend for any production
Loki deployment because it scales infinitely, is cheap, and is durable. For a
kind cluster running locally, there is no S3 bucket. Filesystem storage writes
chunks to a PVC on the node — simple and sufficient for development and small
production deployments. The `10Gi` PVC holds several months of logs for a single
ASC. If this were a multi-ASC SaaS product, object storage would be the right
call from day one.

### What is the TSDB store and why schema v13?

Loki needs to index log labels (like `level` and `logger`) so queries can find
relevant chunks without scanning everything. The store type defines what backs
that index. TSDB (Time Series Database, the same format Prometheus uses) is the
current default in Loki 3.x and has better query performance and lower storage
overhead than the older `boltdb-shipper`. Schema v13 is the current version of
Loki's storage schema — it defines the chunk format and index structure. Starting
with the current schema avoids a migration later.

### Why does Promtail run as a DaemonSet?

Promtail's job is to collect logs from every pod on every node. Pod logs are
written to the node's filesystem at `/var/log/pods/<namespace>_<pod>_<uid>/`.
The only way for Promtail to read all pods' logs is to run on every node and
mount that directory. A DaemonSet guarantees exactly one Promtail pod per node.
The Helm chart configures the DaemonSet and the necessary `hostPath` volume
mount automatically — no manual manifest writing needed.

### What is the CRI log format and why does the pipeline start with `cri: {}`?

containerd (the container runtime in modern Kubernetes clusters, including kind)
wraps every line a container writes to stdout/stderr before writing it to the
node's log file. The format is:

```
2024-01-01T12:00:00.000000000Z stdout F {"timestamp": "...", "level": "INFO", ...}
```

Fields: `<RFC3339 timestamp> <stream: stdout|stderr> <tag: F=full|P=partial> <log content>`

The `cri: {}` Promtail pipeline stage parses and strips this wrapper, leaving
only the actual log content (`{"timestamp": "...", "level": "INFO", ...}`) for
the subsequent JSON stage. Without `cri: {}`, the `json` stage would try to
parse the entire CRI-wrapped line as JSON and fail.

### Why parse only `level` and `logger` as labels, not `message` or `timestamp`?

Loki's design is fundamentally different from Elasticsearch: it indexes labels
(key=value pairs attached to log streams), not the full text of log lines. This
makes Loki dramatically cheaper to run — it stores compressed chunks of raw log
lines and only indexes the labels.

The tradeoff is that label cardinality must be kept low. Every unique combination
of label values creates a separate log stream with its own index entry. `level`
has ~5 possible values (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
`logger` has ~4 values (`timer.api`, `timer.auth`, `timer.audit`, `django`).
That's at most ~20 streams — perfectly manageable.

If we also indexed `message` (which is unique per log line), Loki would create
a new stream for every single log line, completely defeating its indexing model
and making it as expensive as Elasticsearch. High-cardinality values (user IDs,
request IDs, operation IDs) belong in the log line body, not in labels. Grafana
queries use label filters to narrow to a stream and then regex/text filters to
search within the body.

### Why does the JSON stage fail silently on non-JSON lines?

nginx (the frontend container) emits plain-text access logs like:
```
172.16.0.1 - - [01/Jan/2024:12:00:00 +0000] "GET / HTTP/1.1" 200 1234
```

The `json` Promtail stage attempts to parse every log line as JSON. When
parsing fails (non-JSON input), it simply skips extraction — the `level` and
`logger` labels are absent for that line, but the line is still shipped to Loki
and stored. This means you can still query nginx logs in Grafana; they just
won't have `level`/`logger` label filters available.

---

## Step 9 — Grafana + pre-built dashboards

### Why provision the Loki datasource in Helm values instead of the UI?

Grafana supports "provisioning" — loading configuration from files on startup
rather than through the UI. Provisioned datasources appear automatically in
every fresh Grafana install. Without provisioning, every time Grafana restarts
with a fresh PVC (or in a new cluster), someone would have to manually add the
Loki datasource through the UI. Provisioning makes the setup reproducible and
codified. The `datasources.yaml` key in the Helm values maps directly to a file
Grafana reads on startup.

### Why use the sidecar pattern for dashboards instead of baking them into Helm values?

The alternative to the sidecar is putting dashboard JSON inline in the Helm
values under a `dashboards:` key. This works but has a downside: to update a
dashboard, you'd have to run `helm upgrade` to push the new values. The sidecar
approach watches for ConfigMaps labeled `grafana_dashboard=1` in the namespace
and hot-loads them without a Helm upgrade. In practice for kind, both work
equally well — but the sidecar pattern is the standard in production clusters
where dashboards evolve independently of the Grafana release.

The flow is: `apply.sh` creates a ConfigMap from the JSON files in
`k8s/logging/dashboards/` and labels it. The Grafana sidecar container (running
alongside Grafana in the same pod) detects the new ConfigMap and writes the
JSON to `/var/lib/grafana/dashboards/`. Grafana's dashboard provider picks
them up within seconds.

### Why two separate dashboards instead of one?

The audit and API streams answer different questions for different audiences:

- **Audit Events** is for an administrator or compliance role. It answers
  "who did what" — which surgeons logged in, how many operations were performed,
  whether login failures are occurring. The audience is non-technical.
- **API Requests** is for a developer or on-call engineer. It answers "is the
  system healthy" — request rate, error rate, response time. The audience is
  technical.

Combining them would produce a cluttered dashboard that serves neither audience
well.

### How do the dashboard queries connect to the Promtail pipeline?

The pipeline in Step 8 promotes `level` and `logger` from JSON fields to Loki
labels. Dashboard queries use those labels as stream selectors:

```logql
{namespace="timer", logger="timer.audit"}
```

`namespace` and `app` are added automatically by Promtail from Kubernetes pod
metadata. `logger` and `level` are added by the JSON + labels pipeline stages.
Without those pipeline stages, the only way to filter to audit events would be
a slow full-text search (`|= "timer.audit"`) instead of a fast label index
lookup.

### What is `$__range` in the stat panel queries?

`$__range` is a Grafana built-in template variable that equals the currently
selected time range. If you are viewing "Last 6 hours", `$__range` becomes
`6h`. This makes the stat panels show counts for whatever time window you are
looking at, rather than a hardcoded window. It automatically updates when you
change the time range picker.

### What is `unwrap duration_ms` and why does it enable the response time panel?

Standard LogQL metric queries count log lines (e.g., `count_over_time`,
`rate`). To compute averages or percentiles over a *numeric field inside* a
log line, LogQL needs to extract that number first. `| json` parses the JSON
log line and makes all fields available. `| unwrap duration_ms` tells LogQL to
use the `duration_ms` field as the metric value for aggregation:

```logql
avg_over_time({...} | json | unwrap duration_ms [1m])
```

This computes the average `duration_ms` across all log lines in each 1-minute
window — effectively a per-minute average response time chart, derived entirely
from log data with no separate metrics system required.

The p95 panel uses `quantile_over_time(0.95, ...)` — the 95th percentile
response time, which is more meaningful than the average for catching tail
latency issues.

### Why is Grafana accessed via port-forward rather than the Ingress?

The Ingress in Step 7 routes `timer.local` to the frontend Service. Adding
Grafana to the same Ingress would require either a second hostname
(e.g., `grafana.timer.local`) or a path prefix (`timer.local/grafana/`). Both
require nginx-ingress configuration and `/etc/hosts` changes. Port-forward is
simpler for a tool that only the developer or system administrator needs to
access — it does not need to be publicly reachable. For a production deployment
serving multiple engineers, adding a Grafana Ingress rule with authentication
(Grafana's built-in login is sufficient) would be the next step.

---

## Step 10 — kind cluster config + apply scripts

### Why does `kind-config.yaml` set `node-labels: "ingress-ready=true"`?

When ingress-nginx runs with `hostPort.enabled=true`, it binds ports 80 and
443 directly on the Kubernetes node's network interface. In a multi-node
cluster, only one node should do this — you can't bind the same host port on
two nodes simultaneously. ingress-nginx uses a node selector (`ingress-ready=true`)
to decide which node gets the hostPort pods. The `kubeadmConfigPatches` block
in `kind-config.yaml` applies that label during cluster bootstrap. Without it,
the ingress-nginx controller pod stays in `Pending` forever because no node
matches its node selector.

### Why does `kind-config.yaml` use `extraPortMappings` instead of LoadBalancer?

Kind runs Kubernetes nodes as Docker containers. `extraPortMappings` tells
Docker to forward host port 80 → the node container's port 80, and 443 → 443.
When ingress-nginx binds port 80 on the node (via hostPort), that traffic is
reachable from your host browser at `https://timer.local`.

A LoadBalancer service normally requires a cloud provider to provision an
external IP. Kind has no cloud provider. The hostPort + Docker port-mapping
combination is the standard workaround for exposing services from kind.

### Why must Docker Compose be stopped before running `setup-kind.sh`?

The kind cluster's ingress-nginx pod binds ports 80 and 443 on the host
machine. The Docker Compose `frontend` service (from M5) also binds port 80.
Only one process can hold a port at a time. If Docker Compose is running,
the hostPort bind fails silently and the ingress controller is unreachable.
Run `docker compose down` before running `setup-kind.sh`.

### Why use `helm upgrade --install` instead of `helm install`?

`helm install` fails if a release already exists. `helm upgrade --install`
installs if not present and upgrades if already installed — making
`setup-kind.sh` safe to re-run after a chart update without erroring.

### Why does metrics-server need `--kubelet-insecure-tls` in kind?

metrics-server scrapes CPU and memory usage from each node's kubelet over
HTTPS. In production, the kubelet's TLS certificate is signed by the cluster
CA. In kind, the kubelet uses a self-signed certificate that metrics-server
cannot verify, so scraping fails. `--kubelet-insecure-tls` skips TLS
verification for kubelet connections. This flag is kind-specific — never use
it in production. Without it, the HPA shows `<unknown>` CPU utilization and
never scales.

### Why delete and recreate the migration Job on every `apply.sh` run?

Kubernetes Jobs are immutable after creation — `kubectl apply` cannot update an
existing Job. More importantly, a completed Job does not re-run when the same
manifest is re-applied. On a new release that includes schema migrations,
`apply.sh` must delete the old completed Job so the new one runs. `kubectl
delete job --ignore-not-found` is safe: if no Job exists (first run) it
succeeds silently; if one exists it deletes it so the new `apply` creates a
fresh one.

### Why are ClusterIssuers applied in `apply.sh` rather than `setup-kind.sh`?

ClusterIssuers are cert-manager resources that depend on cert-manager's CRDs
(installed in `setup-kind.sh`). They are application-level config — they
reference the Let's Encrypt email address and the issuer name used by the
Ingress — so they belong with the application manifests rather than cluster
infrastructure. They are applied after migrations succeed but before the
Ingress is created, by which point cert-manager's webhook has had time to
become ready.

### Why wait 180 seconds for backend pods but only 60 for frontend?

The backend pod runs `entrypoint.sh` before gunicorn: wait for postgres,
run `migrate`, start gunicorn, pass the readiness probe. On a cold kind
cluster this takes 30–60 seconds. The readiness probe adds another 15s
initial delay plus up to 30s of retries. 180 seconds gives comfortable
headroom. The frontend nginx starts in under a second — 60 seconds covers
any image load delay with room to spare.
