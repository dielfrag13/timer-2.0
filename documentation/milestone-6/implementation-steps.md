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

**Status: Planned**

- `k8s/namespace.yaml` — creates the `timer` namespace
- `k8s/configmap.yaml` — non-sensitive env vars: `DEBUG`, `LOG_LEVEL`,
  `ALLOWED_HOSTS`, `DJANGO_SETTINGS_MODULE`
- `k8s/secret.example.yaml` — placeholder template for `SECRET_KEY` and
  `DATABASE_URL`; actual `k8s/secret.yaml` is `.gitignore`'d
- `backend/timer_server/settings.py` — add `SECURE_PROXY_SSL_HEADER` so
  Django correctly identifies HTTPS requests forwarded by nginx-ingress

---

## Step 3 — PostgreSQL StatefulSet + Service

**Status: Planned**

- `k8s/postgres/statefulset.yaml` — StatefulSet with `volumeClaimTemplates`
  for a 10 Gi PVC; pod named `postgres-0`; credentials from the Secret
- `k8s/postgres/service.yaml` — ClusterIP Service named `postgres`; the
  `DATABASE_URL` in the Secret points to `postgres:5432`

---

## Step 4 — Migration Job

**Status: Planned**

- `k8s/backend/migration-job.yaml` — Kubernetes `Job` that runs
  `python manage.py migrate` once; `restartPolicy: OnFailure`;
  `backoffLimit: 3`; uses the same ConfigMap + Secret as the backend

---

## Step 5 — Backend Deployment + Service + HPA

**Status: Planned**

- `k8s/backend/deployment.yaml` — 2 replicas; `envFrom` ConfigMap + Secret;
  readiness and liveness probes on `GET /health/`; CPU/memory resource requests
- `k8s/backend/service.yaml` — ClusterIP named `backend` on port 8000
- `k8s/backend/hpa.yaml` — scales 2–6 replicas at 70% average CPU

---

## Step 6 — Frontend Deployment + Service

**Status: Planned**

- `k8s/frontend/deployment.yaml` — 1 replica of the nginx image from M5;
  existing `nginx.conf` works unchanged (K8s DNS resolves `backend` the same
  way Docker Compose does)
- `k8s/frontend/service.yaml` — ClusterIP named `frontend` on port 80

---

## Step 7 — cert-manager + nginx-ingress + Ingress

**Status: Planned**

- Install `ingress-nginx` and `cert-manager` via Helm
- `k8s/ingress/clusterissuer-selfsigned.yaml` — self-signed issuer for kind
- `k8s/ingress/clusterissuer-letsencrypt.yaml` — Let's Encrypt issuer for
  production (HTTP-01 challenge)
- `k8s/ingress/ingress.yaml` — routes all traffic to the frontend Service;
  TLS annotation triggers cert-manager

---

## Step 8 — Loki + Promtail

**Status: Planned**

- `k8s/logging/loki-values.yaml` — single-binary Loki, filesystem storage,
  auth disabled (internal cluster only)
- `k8s/logging/promtail-values.yaml` — scrapes pod logs from
  `/var/log/pods/`; parses `level` and `logger` JSON fields as labels;
  ships to `loki.logging.svc.cluster.local:3100`

---

## Step 9 — Grafana + pre-built dashboards

**Status: Planned**

- `k8s/logging/grafana-values.yaml` — provisions Loki datasource; mounts
  dashboard JSONs from a ConfigMap
- `k8s/logging/dashboards/audit.json` — login events, operation lifecycle
  events from the `timer.audit` log stream
- `k8s/logging/dashboards/api-requests.json` — request rate, error rate,
  slow queries from the `timer.api` log stream

---

## Step 10 — kind cluster + apply scripts + local validation

**Status: Planned**

- `k8s/kind-config.yaml` — single-node kind cluster with host port mappings
  80 → 80 and 443 → 443
- `k8s/scripts/build-images.sh` — builds backend and frontend Docker images
  locally and loads them into the kind cluster
- `k8s/scripts/setup-kind.sh` — creates the kind cluster; installs
  ingress-nginx and metrics-server via Helm; waits for ingress-nginx ready
- `k8s/scripts/apply.sh` — applies all manifests in dependency order with
  `kubectl wait` gates between steps

---

## Step 11 — Docs: milestones.md + running-and-testing.md

**Status: Planned**

- `documentation/milestones.md` — M6 status → Complete
- `documentation/milestone-6/running-and-testing.md` — prerequisites,
  full local setup walkthrough, how to target a real cloud cluster, Grafana
  access, manual test checklist
