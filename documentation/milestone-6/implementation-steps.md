# Milestone 6 — Implementation Steps

## Step 1 — Tooling + `k8s/` directory structure + docs

**Status: Complete**

Installed: `kubectl`, `kind`, `helm` (see running-and-testing.md for commands).
Created the full `k8s/` directory tree and this documentation.

**`k8s/` directory layout:**
```
k8s/
  kind-config.yaml             ← kind cluster (port mappings, single node)
  namespace.yaml
  configmap.yaml
  secret.example.yaml          ← template; actual secret.yaml is .gitignore'd
  postgres/
    statefulset.yaml
    service.yaml
  backend/
    migration-job.yaml
    deployment.yaml
    service.yaml
    hpa.yaml
  frontend/
    deployment.yaml
    service.yaml
  ingress/
    clusterissuer-selfsigned.yaml
    clusterissuer-letsencrypt.yaml
    ingress.yaml
  logging/
    loki-values.yaml
    promtail-values.yaml
    grafana-values.yaml
    dashboards/
      audit.json
      api-requests.json
  scripts/
    build-images.sh
    setup-kind.sh
    apply.sh
```

---

## Step 2 — Namespace, ConfigMap, Secret

**Status: Complete**

- `k8s/namespace.yaml` — creates the `timer` namespace
- `k8s/configmap.yaml` — non-sensitive env vars: `DEBUG`, `LOG_LEVEL`,
  `ALLOWED_HOSTS`; `ALLOWED_HOSTS` must match the hostname in `ingress.yaml`
  (default: `timer.local` for kind, update to real domain for production)
- `k8s/secret.example.yaml` — template for `SECRET_KEY` and `DATABASE_URL`;
  copy to `k8s/secret.yaml`, fill in real values; `secret.yaml` is
  `.gitignore`'d and must never be committed
- `backend/timer_server/settings.py` — added `SECURE_PROXY_SSL_HEADER` so
  Django trusts the `X-Forwarded-Proto` header set by nginx-ingress, making
  `request.is_secure()` and the `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE`
  flags work correctly behind TLS termination

---

## Step 3 — PostgreSQL StatefulSet + Service

**Status: Complete**

- `k8s/postgres/statefulset.yaml` — StatefulSet (1 replica); credentials
  pulled from `timer-secret` (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_DB`); `PGDATA` set to a subdirectory of the mount to avoid
  the lost+found issue; readiness + liveness probes via `pg_isready`;
  10 Gi `volumeClaimTemplates` PVC
- `k8s/postgres/service.yaml` — ClusterIP Service named `postgres` on
  port 5432; `DATABASE_URL` in the Secret uses `postgres` as the hostname
- `k8s/secret.example.yaml` — updated to include `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_DB` alongside the existing Django fields

---

## Step 4 — Migration Job

**Status: Complete**

- `k8s/backend/migration-job.yaml` — Kubernetes `Job`; uses the backend
  image with CMD overridden to `true`; the existing `entrypoint.sh` already
  waits for Postgres and runs `migrate` before calling `exec "$@"`, so
  `exec true` exits 0 cleanly after migrations finish; `restartPolicy:
  OnFailure`; `backoffLimit: 3`; `ttlSecondsAfterFinished: 300` (pod
  auto-deletes after 5 minutes); `envFrom` ConfigMap + Secret

---

## Step 5 — Backend Deployment + Service + HPA

**Status: Complete**

- `k8s/backend/deployment.yaml` — 2 replicas; `timer-backend:latest`
  (`imagePullPolicy: Never` for kind); `envFrom` ConfigMap + Secret;
  readiness probe on `GET /health/` (initialDelay 15s to allow entrypoint.sh
  to finish); liveness probe same path (initialDelay 60s so a slow cold
  start is not mistaken for a crash); 256Mi/500m requests, 512Mi/500m limits
- `k8s/backend/service.yaml` — ClusterIP named `backend` on port 8000;
  `backend` is the hostname the frontend nginx.conf proxies to
- `k8s/backend/hpa.yaml` — `autoscaling/v2`; scales 2–6 replicas at 70%
  average CPU; requires metrics-server (installed in Step 10)

---

## Step 6 — Frontend Deployment + Service

**Status: Complete**

- `k8s/frontend/deployment.yaml` — 1 replica; `timer-frontend:latest`
  (`imagePullPolicy: Never`); no env injection needed (config baked into
  image at build time); readiness + liveness probes on `GET /` port 80;
  lightweight resource limits (64Mi/50m requests, 128Mi/100m limits)
- `k8s/frontend/service.yaml` — ClusterIP named `frontend` on port 80;
  the Ingress (Step 7) routes all external traffic here; `nginx.conf`
  works unchanged because K8s DNS resolves `backend` the same way Docker
  Compose does

---

## Step 7 — cert-manager + nginx-ingress + Ingress

**Status: Complete**

- `k8s/ingress/clusterissuer-selfsigned.yaml` — self-signed issuer for kind;
  browser will warn but HTTPS works; no external authority required
- `k8s/ingress/clusterissuer-letsencrypt.yaml` — Let's Encrypt ACME HTTP-01
  issuer for production; automatic issuance and renewal; switch to staging
  server first to avoid rate limits during setup
- `k8s/ingress/ingress.yaml` — `ingressClassName: nginx`; all traffic routed
  to the frontend Service (nginx handles internal `/api/` proxying); TLS with
  `secretName: timer-tls`; annotation `cert-manager.io/cluster-issuer:
  selfsigned` (change to `letsencrypt-prod` for production); host `timer.local`
  (add to `/etc/hosts` for kind)
- Helm installs of ingress-nginx and cert-manager are handled in Step 10
  (`setup-kind.sh`)

---

## Step 8 — Loki + Promtail

**Status: Complete**

- `k8s/logging/loki-values.yaml` — single-binary deployment mode; 1 replica;
  `auth_enabled: false` (single-tenant); filesystem storage on a 10Gi PVC;
  TSDB index with schema v13; gateway, test pod, and canary all disabled
- `k8s/logging/promtail-values.yaml` — DaemonSet configured by Helm chart;
  3-stage pipeline: `cri: {}` (strip containerd wrapper) → `json` (extract
  `level` and `logger` from Django's JSON log lines) → `labels` (promote to
  Loki index labels); pushes to `loki.logging.svc.cluster.local:3100`; non-
  JSON lines (nginx) fail the json stage silently and are still stored

---

## Step 9 — Grafana + pre-built dashboards

**Status: Complete**

- `k8s/logging/grafana-values.yaml` — provisions Loki datasource (uid: loki,
  isDefault: true); sidecar watches `grafana_dashboard=1` ConfigMaps in
  `logging` namespace and hot-loads dashboards; admin/admin credentials for
  kind dev; access via `kubectl port-forward svc/grafana 3000:80 -n logging`
- `k8s/logging/dashboards/audit.json` — 3 stat panels (total events, login
  failures, operations completed); bar chart of logins/starts/completions/
  failures over time; scrollable raw log panel; queries use exact event names
  from views.py (`login_failure`, `operation_create`, `operation_complete`)
- `k8s/logging/dashboards/api-requests.json` — 3 stat panels (total requests,
  5xx errors, 4xx warnings); request rate time series (all/error/warning);
  avg + p95 response time via `unwrap duration_ms`; error/warning log panel
- `documentation/milestone-6/grafana-guide.md` — full user guide: accessing
  Grafana, what to expect on first load, panel-by-panel explanation of both
  dashboards, LogQL query cookbook, post-deployment health checklist

---

## Step 10 — kind cluster + apply scripts + local validation

**Status: Complete**

- `k8s/kind-config.yaml` — single control-plane node; `ingress-ready=true`
  node label (required for ingress-nginx hostPort); port mappings 80→80 and
  443→443 via Docker extraPortMappings
- `k8s/scripts/setup-kind.sh` — creates cluster; adds Helm repos; installs
  ingress-nginx (hostPort + ClusterIP + ingress-ready node selector),
  cert-manager (with CRDs), metrics-server (kubelet-insecure-tls for kind),
  Loki, Promtail, Grafana; creates and labels dashboard ConfigMap; all
  Helm installs use `upgrade --install` for idempotency
- `k8s/scripts/build-images.sh` — builds `timer-backend:latest` and
  `timer-frontend:latest`; loads both into the named kind cluster via
  `kind load docker-image`; validates cluster exists before loading
- `k8s/scripts/apply.sh` — applies in order: namespace → configmap → secret
  → postgres → wait → migration Job (delete+recreate) → wait → ClusterIssuers
  → backend → wait → frontend → wait → Ingress; prints access instructions;
  errors with helpful messages on secret missing or Job failure
- Run order: `setup-kind.sh` → `build-images.sh` → `apply.sh`

---

## Step 11 — Docs: milestones.md + running-and-testing.md

**Status: Complete**

- `documentation/milestones.md` — M6 status → Complete with full key outcomes
- `documentation/milestone-6/running-and-testing.md` — prerequisites table;
  7-step first-time setup walkthrough; subsequent-run flow; cluster health
  commands; TLS/cert verification; HPA verification; Grafana access; cluster
  teardown; Docker Compose switch-back table; cloud cluster migration guide
  (image registry, imagePullPolicy, hostname, ClusterIssuer, managed DB);
  8-section manual test checklist including infrastructure, full M5 app flow,
  logging, and optional HPA scaling verification
