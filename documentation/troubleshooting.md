# Timer 2.0 — Troubleshooting Log

A running record of problems encountered during development, their root cause,
and how they were resolved. Updated each milestone step.

---

## M5 Step 12 — npm command failed with `ENOENT`

**Symptom:** Running `npm run build` (or any npm command) returned a "no such
file or directory" error immediately.

**Root cause:** After running `pytest` from the `backend/` directory, the shell's
working directory remained at `backend/`. npm commands must be run from the
`frontend/` directory where `package.json` lives.

**Fix:** Always run npm commands from `frontend/`:
```bash
cd frontend
source ~/.nvm/nvm.sh && npm run build
```
Or use an absolute path:
```bash
source ~/.nvm/nvm.sh && npm --prefix /path/to/timer-2.0/frontend run build
```

---

## M5 Step 13 — Vim swap file appeared as untracked before commit

**Symptom:** `git status` showed `.running-and-testing.md.swp` as an untracked
file just before the M5 commit.

**Root cause:** Vim (or a tool that uses Vim) was open on the file and left a
swap file in the same directory. Git does not ignore these by default.

**Fix:** Added editor swap and backup file patterns to `.gitignore`:
```
*.swp
*.swo
*~
```

---

## M5 Step 13 — Docker Compose backend cannot reach database

**Symptom:** After running `docker compose up --build`, the backend container
logged `localhost:5432 - no response` repeatedly and the service failed to start.

**Root cause:** `backend/.env` had `DATABASE_URL=postgres://timer:password@localhost:5432/timer`.
Inside a Docker container, `localhost` refers to the container itself, not the
host machine. The Postgres container is reachable by its Docker Compose service
name (`db`), not `localhost`.

**Fix:** Change the host in `DATABASE_URL` to match the environment:

| Environment | `DATABASE_URL` host |
|---|---|
| Local dev / pytest | `localhost` |
| Docker Compose | `db` |
| Kubernetes | `postgres` |

Update `backend/.env` before switching environments:
```
DATABASE_URL=postgres://timer:password@db:5432/timer
```

---

## M6 Step 10 — `apply.sh` times out on old terminating pods during rolling update

**Symptom:** After fixing the `DisallowedHost` probe issue and re-running
`apply.sh`, one new pod became ready but the wait step still timed out:
```
pod/backend-698ddb8ff8-pbjr7 condition met
timed out waiting for the condition on pods/backend-79fb96c8f4-rpl44
timed out waiting for the condition on pods/backend-79fb96c8f4-tgjvr
```

**Root cause:** `kubectl wait --selector=app=backend` matches all pods with
that label, including pods from the old ReplicaSet that are being terminated
as part of the rolling update. Terminating pods never become `Ready` — they
time out. `kubectl wait pod` is the wrong tool for watching a Deployment
rollout.

**Fix:** Replace `kubectl wait pod --selector` with `kubectl rollout status
deployment/<name>` for both backend and frontend in `apply.sh`. `rollout
status` tracks only the current ReplicaSet's progress — it waits until the
desired number of new pods are Ready and exits successfully. It works correctly
for both fresh deploys and rolling updates.

---

## M6 Step 10 — Backend readiness probe failing with `DisallowedHost`

**Symptom:** `apply.sh` timed out waiting for backend pods. Backend logs showed:
```
django.core.exceptions.DisallowedHost: Invalid HTTP_HOST header: '10.244.0.23:8000'.
You may need to add '10.244.0.23' to ALLOWED_HOSTS.
```
The readiness probe was returning 400, so pods never became Ready.

**Root cause:** Kubernetes readiness/liveness probes hit the pod directly at
its cluster IP (e.g., `10.244.0.23:8000`), bypassing the Ingress and nginx.
The probe's HTTP request uses the pod IP as the `Host` header. Django's
`ALLOWED_HOSTS` only contained `timer.local`, so every probe request was
rejected with `DisallowedHost` before it could reach the `/health/` view.

**Fix — two changes:**

1. `k8s/configmap.yaml` — add `localhost` to `ALLOWED_HOSTS`:
   ```
   ALLOWED_HOSTS: "timer.local,localhost"
   ```

2. `k8s/backend/deployment.yaml` — add `Host: localhost` header to both
   readiness and liveness probes so Django sees a known host:
   ```yaml
   httpGet:
     path: /health/
     port: 8000
     httpHeaders:
       - name: Host
         value: localhost
   ```

`localhost` is always a safe value for internal cluster health checks. Pod IPs
are dynamic and cannot be predicted, so they cannot be added to `ALLOWED_HOSTS`.

---

## M6 Step 10 — Grafana dashboard ConfigMap label value contains a space

**Symptom:** `setup-kind.sh` failed at the dashboard loading step with:
```
error: invalid label value: "grafana_folder=Timer 2.0": a valid label must be
an empty string or consist of alphanumeric characters, '-', '_' or '.'...
```

**Root cause:** Kubernetes label values cannot contain spaces. The folder name
`"Timer 2.0"` was being set as a label, but the Grafana sidecar reads the
folder name from an **annotation**, not a label. Annotations have no character
restrictions on values.

**Fix:** Set `grafana_folder` with `kubectl annotate` instead of including it
in `kubectl label`. The sidecar is already configured with `folderAnnotation:
grafana_folder` in `grafana-values.yaml` — it reads annotations, not labels.
Updated in `k8s/scripts/setup-kind.sh`.

**Side note:** The Grafana persistence warning (`WARNING: Persistence is
disabled!!! You will lose your data when the Grafana pod is terminated`) was
also fixed by adding `persistence.enabled: true` to `grafana-values.yaml`.

---

## M6 Step 10 — ingress-nginx node selector type error

**Symptom:** `setup-kind.sh` failed during ingress-nginx installation with:
```
server-side apply failed ... .spec.template.spec.nodeSelector.ingress-ready:
expected string, got &value.valueUnstructured{Value:true}
```

**Root cause:** Helm's `--set` flag auto-detects value types. The value `true`
is parsed as a boolean, but Kubernetes requires all node selector values to be
strings. The server-side apply validation caught the type mismatch.

**Fix:** Use `--set-string` instead of `--set` for the node selector value.
`--set-string` forces Helm to treat the value as a string regardless of content:
```bash
--set-string "controller.nodeSelector.ingress-ready=true"
```
Updated in `k8s/scripts/setup-kind.sh`.

---

## M6 Step 1 — Helm `baltocdn.com` apt repository is deprecated

**Symptom:** The Helm install commands using `https://baltocdn.com/helm/signing.asc`
and the `baltocdn.com` apt repo either failed or installed an outdated version.

**Root cause:** The `baltocdn.com` Helm apt repository is no longer maintained.
Helm moved its official Debian packages to Buildkite's package hosting at
`https://packages.buildkite.com/helm-linux/helm-debian/`.

**Fix:** Use the updated install commands (now reflected in
`documentation/dependencies.md`):
```bash
HELM_BUILDKITE_APT_KEY_ID="DDF78C3E6EBB2D2CC223C95C62BA89D07698DBC6"

sudo apt-get install -y curl gpg apt-transport-https

curl -fsSL https://packages.buildkite.com/helm-linux/helm-debian/gpgkey > "${TMPDIR:-/tmp}/helm.gpg"

if [ "$(gpg --show-keys --with-colons "${TMPDIR:-/tmp}/helm.gpg" | awk -F: '$1 == "fpr" {print $10}' | head -n 1)" != "${HELM_BUILDKITE_APT_KEY_ID}" ]; then
  echo "ERROR: Unexpected Helm APT key ID: potential key compromise"
  exit 1
fi

cat "${TMPDIR:-/tmp}/helm.gpg" | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null

echo "deb [signed-by=/usr/share/keyrings/helm.gpg] https://packages.buildkite.com/helm-linux/helm-debian/any/ any main" \
  | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list

sudo apt-get update && sudo apt-get install -y helm
```

The key fingerprint check (`DDF78C3E6EBB2D2CC223C95C62BA89D07698DBC6`) guards
against a compromised repository injecting a different signing key.
