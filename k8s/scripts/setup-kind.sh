#!/usr/bin/env bash
# Create the kind cluster and install all third-party tooling via Helm.
# Run this once per cluster. Re-running is safe — helm upgrade --install
# is idempotent and kind create cluster will error if the cluster exists
# (which is caught below).
#
# Usage: k8s/scripts/setup-kind.sh [cluster-name]
#   cluster-name defaults to "timer"
#
# IMPORTANT: Stop any Docker Compose stack using ports 80/443 before running:
#   docker compose down
set -euo pipefail

CLUSTER_NAME="${1:-timer}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── 1. Kind cluster ──────────────────────────────────────────────────────────

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  echo "Kind cluster '$CLUSTER_NAME' already exists — skipping creation."
else
  echo "==> Creating kind cluster '$CLUSTER_NAME'..."
  kind create cluster --name "$CLUSTER_NAME" --config "$REPO_ROOT/k8s/kind-config.yaml"
fi

# ── 2. Helm repos ────────────────────────────────────────────────────────────

echo "==> Adding / updating Helm repos..."
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx        2>/dev/null || true
helm repo add cert-manager  https://charts.jetstack.io                        2>/dev/null || true
helm repo add grafana       https://grafana.github.io/helm-charts             2>/dev/null || true
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server 2>/dev/null || true
helm repo update

# ── 3. ingress-nginx ─────────────────────────────────────────────────────────

echo "==> Installing ingress-nginx..."
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.hostPort.enabled=true \
  --set controller.service.type=ClusterIP \
  --set-string "controller.nodeSelector.ingress-ready=true"

echo "==> Waiting for ingress-nginx controller to be ready (up to 120s)..."
kubectl wait \
  --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s

# ── 4. cert-manager ──────────────────────────────────────────────────────────

echo "==> Installing cert-manager..."
helm upgrade --install cert-manager cert-manager/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true

echo "==> Waiting for cert-manager pods to be ready (up to 120s)..."
kubectl wait \
  --namespace cert-manager \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/instance=cert-manager \
  --timeout=120s

# ── 5. metrics-server ────────────────────────────────────────────────────────
# --kubelet-insecure-tls is required in kind because the kubelet uses a
# self-signed certificate that metrics-server cannot verify.

echo "==> Installing metrics-server..."
helm upgrade --install metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  --set 'args={--kubelet-insecure-tls}'

# ── 6. Loki ──────────────────────────────────────────────────────────────────

echo "==> Installing Loki..."
helm upgrade --install loki grafana/loki \
  --namespace logging \
  --create-namespace \
  --values "$REPO_ROOT/k8s/logging/loki-values.yaml"

# ── 7. Promtail ──────────────────────────────────────────────────────────────

echo "==> Installing Promtail..."
helm upgrade --install promtail grafana/promtail \
  --namespace logging \
  --values "$REPO_ROOT/k8s/logging/promtail-values.yaml"

# ── 8. Grafana ───────────────────────────────────────────────────────────────

echo "==> Installing Grafana..."
helm upgrade --install grafana grafana/grafana \
  --namespace logging \
  --values "$REPO_ROOT/k8s/logging/grafana-values.yaml"

# ── 9. Grafana dashboard ConfigMap ───────────────────────────────────────────
# Delete and recreate so re-runs pick up any JSON changes.

echo "==> Loading Grafana dashboards..."
kubectl delete configmap timer-dashboards --namespace logging --ignore-not-found
kubectl create configmap timer-dashboards \
  --from-file="$REPO_ROOT/k8s/logging/dashboards/" \
  --namespace logging
# Label tells the sidecar to pick up this ConfigMap as a dashboard source.
# Folder name goes on an annotation — label values cannot contain spaces.
kubectl label configmap timer-dashboards \
  grafana_dashboard=1 \
  --namespace logging
kubectl annotate configmap timer-dashboards \
  grafana_folder="Timer 2.0" \
  --namespace logging

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Cluster setup complete!"
echo ""
echo "Next steps:"
echo "  1. k8s/scripts/build-images.sh   — build and load application images"
echo "  2. k8s/scripts/apply.sh          — deploy the application"
