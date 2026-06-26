#!/usr/bin/env bash
# Build the backend and frontend Docker images and load them into the kind
# cluster. Must be run after setup-kind.sh creates the cluster.
#
# Usage: k8s/scripts/build-images.sh [cluster-name]
#   cluster-name defaults to "timer"
set -euo pipefail

CLUSTER_NAME="${1:-timer}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Verify the cluster exists before trying to load images.
if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  echo "ERROR: kind cluster '$CLUSTER_NAME' not found."
  echo "Run k8s/scripts/setup-kind.sh first."
  exit 1
fi

echo "==> Building backend image (timer-backend:latest)..."
docker build -t timer-backend:latest "$REPO_ROOT/backend"

echo "==> Building frontend image (timer-frontend:latest)..."
docker build -t timer-frontend:latest "$REPO_ROOT/frontend"

echo "==> Loading images into kind cluster '$CLUSTER_NAME'..."
echo "    (This copies the images into the kind node container — may take 30–60s)"
kind load docker-image timer-backend:latest --name "$CLUSTER_NAME"
kind load docker-image timer-frontend:latest --name "$CLUSTER_NAME"

echo ""
echo "Images loaded. Run k8s/scripts/apply.sh to deploy the application."
