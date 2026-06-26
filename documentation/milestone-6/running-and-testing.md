# Milestone 6 — Running and Testing

This guide covers how to bring up the full Kubernetes stack locally using kind,
how to verify every component, and a manual test checklist. It also briefly
describes what changes when targeting a real cloud cluster.

---

## Prerequisites

All of the following must be installed before starting. See
`documentation/dependencies.md` for exact install commands.

| Tool | Purpose | Verify |
|---|---|---|
| Docker Engine | Runs kind nodes as containers | `docker --version` |
| kubectl | Kubernetes CLI | `kubectl version --client` |
| kind | Local Kubernetes cluster in Docker | `kind version` |
| helm | Installs third-party K8s tools | `helm version` |

Docker Compose (from M4) must also be installed but **must not be running**
during kind cluster use. The kind ingress-nginx pod binds ports 80 and 443 on
the host — if a Docker Compose stack is using port 80 at the same time,
ingress-nginx cannot bind and the cluster is unreachable.

---

## First-time setup

### Step 1 — Stop Docker Compose

If you have the M4/M5 Docker Compose stack running:

```bash
docker compose down
```

### Step 2 — Create the cluster and install tools

```bash
k8s/scripts/setup-kind.sh
```

This takes 3–5 minutes on first run (pulling Helm chart images). It:
- Creates a single-node kind cluster named `timer`
- Installs ingress-nginx, cert-manager, metrics-server, Loki, Promtail, Grafana
- Creates the Grafana dashboard ConfigMap

If it fails partway through, it is safe to re-run — all Helm installs use
`upgrade --install`.

### Step 3 — Build and load application images

```bash
k8s/scripts/build-images.sh
```

This builds `timer-backend:latest` and `timer-frontend:latest` from the local
source, then loads them into the kind cluster's internal image cache. Re-run
this any time you change backend or frontend code.

### Step 4 — Create your secret

```bash
cp k8s/secret.example.yaml k8s/secret.yaml
```

Edit `k8s/secret.yaml`. You must set:

- `SECRET_KEY` — generate one with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
  ```
- `DATABASE_URL` — use the Kubernetes Postgres service hostname:
  ```
  postgres://timer:yourpassword@postgres:5432/timer
  ```
- `POSTGRES_USER` — `timer`
- `POSTGRES_PASSWORD` — same password as in `DATABASE_URL`
- `POSTGRES_DB` — `timer`

`k8s/secret.yaml` is listed in `.gitignore`. Never commit it.

### Step 5 — Deploy the application

```bash
k8s/scripts/apply.sh
```

This applies all manifests in dependency order, waiting for each component
before starting the next. Typical first-run duration is 2–3 minutes. If it
fails, it prints the command to check logs.

### Step 6 — Add `timer.local` to `/etc/hosts`

```bash
echo "127.0.0.1 timer.local" | sudo tee -a /etc/hosts
```

This only needs to be done once per machine. It makes the `timer.local`
hostname (used in the Ingress rule) resolve to localhost, from which Docker
forwards traffic into the kind cluster.

### Step 7 — Open the application

Navigate to `https://timer.local` in your browser.

The browser will warn "Your connection is not private" — this is expected. The
cluster is using a self-signed TLS certificate (the `selfsigned` ClusterIssuer
from Step 7). In Chrome: click **Advanced → Proceed to timer.local (unsafe)**.
In Firefox: click **Advanced → Accept the Risk and Continue**.

Log in with the Django superuser credentials. If you haven't created a
superuser yet, create one now:

```bash
kubectl exec -it deployment/backend -n timer -- python manage.py createsuperuser
```

---

## Subsequent runs

After the cluster and images are already set up, deploying a code change is:

```bash
# Stop Docker Compose if running
docker compose down

# Rebuild only the changed image(s)
k8s/scripts/build-images.sh

# Re-deploy (migrations re-run automatically, no-op if no new migrations)
k8s/scripts/apply.sh
```

If you only changed backend code, the `build-images.sh` still builds both
images but the frontend build is cached by Docker layer caching and is fast.

---

## Checking cluster health

```bash
# Overview of all timer application pods
kubectl get pods -n timer

# Overview of all logging pods
kubectl get pods -n logging

# Overview of ingress-nginx and cert-manager
kubectl get pods -n ingress-nginx
kubectl get pods -n cert-manager
```

All pods should show `Running` and their `READY` column should match their
desired count (e.g., `1/1` or `2/2`). If a pod shows `0/1` in READY but
`Running` in STATUS, it is still starting — wait and re-check.

```bash
# Watch pods update in real time
kubectl get pods -n timer -w

# Describe a pod to see why it's not starting
kubectl describe pod <pod-name> -n timer

# Check backend logs
kubectl logs -l app=backend -n timer --tail=50

# Check a specific pod's logs
kubectl logs <pod-name> -n timer
```

---

## Verifying TLS and the Ingress

```bash
# Check that the TLS certificate was issued
kubectl get certificate -n timer

# The certificate should show READY=True within 30 seconds of apply.sh completing.
# If it stays False, check cert-manager:
kubectl describe certificate timer-tls -n timer
kubectl get certificaterequest -n timer
kubectl logs -l app.kubernetes.io/name=cert-manager -n cert-manager
```

The cert is self-signed so the browser always warns. You can verify the
certificate details by clicking the padlock icon in the browser address bar
(once you've accepted the warning) and checking that the issuer is the
kind cluster's self-signed CA.

---

## Verifying the HPA

```bash
# Check HPA status
kubectl get hpa -n timer
```

After some traffic to the application, the `TARGETS` column should show a
CPU percentage (e.g., `5%/70%`). If it shows `<unknown>/70%`, metrics-server
is not yet collecting data — wait 60 seconds and re-check. The backend starts
with 2 replicas and scales up to 6 if CPU exceeds 70%.

---

## Accessing Grafana

```bash
kubectl port-forward svc/grafana 3000:80 -n logging
```

Leave this running in a separate terminal. Open `http://localhost:3000`.

- Username: `admin`
- Password: `admin`

See `documentation/milestone-6/grafana-guide.md` for a full walkthrough of
the dashboards, what each panel shows, and how to write your own LogQL queries.

---

## Tearing down the cluster

```bash
# Delete the kind cluster entirely (removes all data, images, and K8s resources)
kind delete cluster --name timer

# If you want to bring the Docker Compose stack back up afterwards:
# Edit backend/.env — set DATABASE_URL back to @localhost:5432
docker compose up --build
```

The kind cluster and its PVCs are entirely contained within Docker. Deleting
the cluster is clean and leaves no leftover state on the host machine except
the `/etc/hosts` entry.

---

## Switching back to Docker Compose

The only thing that changes between K8s and Docker Compose is the hostname in
`backend/.env`:

| Environment | `DATABASE_URL` host |
|---|---|
| Local dev / pytest | `localhost` |
| Docker Compose | `db` |
| Kubernetes | `postgres` |

After stopping the kind cluster and running `docker compose up`, update
`backend/.env` to use `@db:5432` and restart the stack.

---

## Targeting a real cloud cluster (GKE, EKS, AKS)

The manifests in `k8s/` work against any standard Kubernetes cluster. The
changes needed for production:

1. **Images**: push to a container registry instead of `kind load`:
   ```bash
   docker build -t gcr.io/your-project/timer-backend:v1.0 ./backend
   docker push gcr.io/your-project/timer-backend:v1.0
   ```
   Update `image:` in `k8s/backend/deployment.yaml` and `k8s/backend/migration-job.yaml`.
   Remove `imagePullPolicy: Never` (or change to `Always`/`IfNotPresent`).

2. **`imagePullPolicy`**: change from `Never` to `IfNotPresent` in
   `k8s/backend/deployment.yaml`, `k8s/backend/migration-job.yaml`, and
   `k8s/frontend/deployment.yaml`.

3. **Ingress hostname**: update `timer.local` to your real domain in
   `k8s/ingress/ingress.yaml` and `ALLOWED_HOSTS` in `k8s/configmap.yaml`.

4. **ClusterIssuer**: change the Ingress annotation from `selfsigned` to
   `letsencrypt-prod` in `k8s/ingress/ingress.yaml`. No other change needed —
   cert-manager handles certificate issuance and renewal automatically.

5. **Secret**: apply `k8s/secret.yaml` via your cloud's secret management
   (AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault, or Sealed Secrets).

6. **Postgres**: for production, consider replacing the StatefulSet with a
   managed database (AWS RDS, GCP Cloud SQL) and removing
   `k8s/postgres/statefulset.yaml`. Update `DATABASE_URL` in the secret to
   point to the managed instance.

7. **`--kubelet-insecure-tls`** for metrics-server: remove this flag. Real
   cloud clusters have proper PKI and metrics-server works without it.

8. **`kind-config.yaml`**: not used. Cloud cluster creation is handled by the
   cloud provider CLI (`gcloud container clusters create`, `aws eks create-cluster`).

---

## Manual test checklist

Run this after every deployment to verify the full stack is working.

### 1. Infrastructure health

| Check | Command | Expected |
|---|---|---|
| All timer pods running | `kubectl get pods -n timer` | All `Running`, all `READY` |
| All logging pods running | `kubectl get pods -n logging` | All `Running`, all `READY` |
| TLS certificate ready | `kubectl get certificate -n timer` | `READY=True` |
| HPA reporting metrics | `kubectl get hpa -n timer` | `TARGETS` shows a percentage, not `<unknown>` |
| `/health/` endpoint | `curl -k https://timer.local/health/` | `{"status": "ok"}` |

---

### 2. Login page (`https://timer.local/login`)

| Check | Expected |
|---|---|
| Navigate to `https://timer.local` (not logged in) | Redirected to `/login` |
| Accept self-signed certificate warning | Page loads normally |
| Submit invalid credentials | Red "Invalid username or password" alert |
| Submit valid admin credentials | Redirected to Dashboard (`/`) |

---

### 3. Full application flow

The application functionality is identical to M5. Run the M5 manual checklist
in `documentation/milestone-5/running-and-testing.md` — sections 3 through 10
(Dashboard through Auth) all apply unchanged.

Key difference: everything runs at `https://timer.local` instead of
`http://localhost` (Docker Compose) or `http://localhost:5173` (local dev).

---

### 4. Logging verification

| Check | Command / Action | Expected |
|---|---|---|
| Promtail collecting logs | `kubectl logs -l app.kubernetes.io/name=promtail -n logging --tail=20` | No errors; lines like "Sending batch..." |
| Loki receiving logs | `kubectl logs loki-0 -n logging --tail=20` | No errors |
| Grafana reachable | `kubectl port-forward svc/grafana 3000:80 -n logging` then open `http://localhost:3000` | Login page loads |
| Loki datasource connected | Grafana → Connections → Data sources → Loki → "Save & test" | "Data source connected and labels found" |
| Dashboards loaded | Grafana → Dashboards | "Timer 2.0" folder with two dashboards |
| Audit events appearing | Open Audit Events dashboard; log in and out of the app; refresh | `login_success` and `logout` events visible in log panel |
| API events appearing | Open API Requests dashboard; navigate around the app; refresh | Request rate non-zero; no 5xx errors |

---

### 5. Scaling verification (optional)

The HPA scales backend pods when CPU exceeds 70%. You can trigger scaling
manually by running a load test:

```bash
# Install hey (HTTP load generator) if not present
# sudo apt-get install hey  (or download binary)

# Run 10,000 requests against the health endpoint
hey -n 10000 -c 50 -k https://timer.local/health/
```

While the load test runs:
```bash
kubectl get hpa -n timer -w
```

You should see the `TARGETS` CPU percentage rise above 70% and the `REPLICAS`
column increase from 2 toward 6. After the load test ends, the HPA scales
back down to 2 replicas within a few minutes (default scale-down stabilization
window is 5 minutes).

---

## Summary checklist

| # | Area | Pass condition |
|---|---|---|
| 1 | Cluster | All pods Running and Ready in `timer` and `logging` namespaces |
| 2 | TLS | Certificate `READY=True`; browser shows HTTPS (with self-signed warning) |
| 3 | Application | Full M5 flow works at `https://timer.local` |
| 4 | Migrations | `apply.sh` migration Job completed; no DB errors in backend logs |
| 5 | Logging | Grafana Loki datasource connected; both dashboards load |
| 6 | Audit trail | Login/logout events visible in Audit Events dashboard |
| 7 | API metrics | Request rate visible in API Requests dashboard; 5xx stat is 0 |
| 8 | HPA | `kubectl get hpa` shows CPU percentage, not `<unknown>` |
