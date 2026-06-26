#!/usr/bin/env bash
# Deploy the timer-2.0 application to the kind cluster.
# Applies all manifests in dependency order with readiness gates between steps.
#
# Prerequisites:
#   - kind cluster running (setup-kind.sh)
#   - Images loaded (build-images.sh)
#   - k8s/secret.yaml exists (copy from k8s/secret.example.yaml and fill in values)
#
# Re-running is safe: kubectl apply is idempotent.
# The migration Job is deleted and recreated on each run so it always executes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Prereq check ─────────────────────────────────────────────────────────────

if [ ! -f "$K8S/secret.yaml" ]; then
  echo "ERROR: k8s/secret.yaml not found."
  echo ""
  echo "Copy the example and fill in real values:"
  echo "  cp k8s/secret.example.yaml k8s/secret.yaml"
  echo "  # edit k8s/secret.yaml — set SECRET_KEY, DATABASE_URL, and Postgres credentials"
  exit 1
fi

# ── 1. Namespace + config ─────────────────────────────────────────────────────

echo "==> Applying namespace, ConfigMap, and Secret..."
kubectl apply -f "$K8S/namespace.yaml"
kubectl apply -f "$K8S/configmap.yaml"
kubectl apply -f "$K8S/secret.yaml"

# ── 2. PostgreSQL ─────────────────────────────────────────────────────────────

echo "==> Applying PostgreSQL..."
kubectl apply -f "$K8S/postgres/service.yaml"
kubectl apply -f "$K8S/postgres/statefulset.yaml"

echo "==> Waiting for PostgreSQL pod to be ready (up to 120s)..."
kubectl wait \
  --namespace timer \
  --for=condition=ready pod \
  --selector=app=postgres \
  --timeout=120s

# ── 3. Migrations ─────────────────────────────────────────────────────────────
# Jobs are immutable once created — delete the old one before re-applying.

echo "==> Running migrations..."
kubectl delete job backend-migrate --namespace timer --ignore-not-found
kubectl apply -f "$K8S/backend/migration-job.yaml"

echo "==> Waiting for migration Job to complete (up to 120s)..."
if ! kubectl wait \
  --namespace timer \
  --for=condition=complete job/backend-migrate \
  --timeout=120s; then
  echo ""
  echo "ERROR: Migration Job did not complete successfully."
  echo "Check the logs:"
  echo "  kubectl logs -l job-name=backend-migrate -n timer"
  exit 1
fi

# ── 4. cert-manager ClusterIssuers ───────────────────────────────────────────

echo "==> Applying ClusterIssuers..."
kubectl apply -f "$K8S/ingress/clusterissuer-selfsigned.yaml"
kubectl apply -f "$K8S/ingress/clusterissuer-letsencrypt.yaml"

# ── 5. Backend ────────────────────────────────────────────────────────────────

echo "==> Applying backend..."
kubectl apply -f "$K8S/backend/deployment.yaml"
kubectl apply -f "$K8S/backend/service.yaml"
kubectl apply -f "$K8S/backend/hpa.yaml"

echo "==> Waiting for backend rollout to complete (up to 180s)..."
kubectl rollout status deployment/backend --namespace timer --timeout=180s

# ── 6. Frontend ───────────────────────────────────────────────────────────────

echo "==> Applying frontend..."
kubectl apply -f "$K8S/frontend/deployment.yaml"
kubectl apply -f "$K8S/frontend/service.yaml"

echo "==> Waiting for frontend rollout to complete (up to 60s)..."
kubectl rollout status deployment/frontend --namespace timer --timeout=60s

# ── 7. Ingress ────────────────────────────────────────────────────────────────

echo "==> Applying Ingress..."
kubectl apply -f "$K8S/ingress/ingress.yaml"

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Deployment complete!"
echo ""
echo "If you haven't already, add timer.local to /etc/hosts:"
echo "  echo '127.0.0.1 timer.local' | sudo tee -a /etc/hosts"
echo ""
echo "Application:  https://timer.local  (accept the self-signed cert warning)"
echo "Grafana:      kubectl port-forward svc/grafana 3000:80 -n logging"
echo "              then open http://localhost:3000  (admin / admin)"
echo ""
echo "To check pod status:"
echo "  kubectl get pods -n timer"
echo "  kubectl get pods -n logging"
