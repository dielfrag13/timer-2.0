# Milestone 6 — Design Decisions

This document explains every technology introduced in Milestone 6: what it is,
what problem it solves, why we chose it over alternatives, and how it fits into
the timer-2.0 production architecture. It is intentionally verbose because all
of this tech is new territory.

---

## Why Kubernetes at all?

After Milestone 5, the application runs perfectly with `docker compose up`. So
why add Kubernetes on top of that?

Docker Compose answers the question "how do I run multiple containers on one
machine?" Kubernetes answers a different question: "how do I run a distributed
application reliably across multiple machines?" The key word is *reliably*.

Here is what Docker Compose cannot do that Kubernetes can:

**Self-healing.** If the backend container crashes, `docker compose` will
restart it (if `restart: unless-stopped` is set), but only on the same machine.
If the machine itself goes down, nothing brings the app back. Kubernetes watches
every pod and restarts it on a healthy node automatically.

**Zero-downtime deploys.** Deploying a new version with Docker Compose means
`docker compose down` followed by `docker compose up`, which drops all traffic
during the gap. Kubernetes does a *rolling update*: it starts new pods, waits
for them to pass their health check, then terminates the old ones — the app
stays available throughout.

**Horizontal scaling.** If load spikes, Docker Compose can't add more backend
containers automatically. Kubernetes's HorizontalPodAutoscaler watches CPU
usage and adds or removes backend pods in real time.

**Declarative state.** You write YAML files describing what you *want* (3
backend replicas, each with 512 MB RAM) and Kubernetes continuously works to
make reality match that description. If a pod is evicted or a node fails,
Kubernetes re-creates what's missing without human intervention.

For a small ASC running timer-2.0, Docker Compose on one server is probably
fine in practice. The value of this milestone is learning the production
deployment pattern so the infrastructure is ready to scale when the ASC grows
or when multiple ASCs use the same system.

---

## The Kubernetes vocabulary

Kubernetes introduces a lot of new nouns. This section explains each one in
terms of what you already know from Docker Compose.

### Cluster

A Kubernetes cluster is a group of machines (called *nodes*) that Kubernetes
manages as a single pool of compute. One node is the *control plane* (runs the
Kubernetes brain — the API server, scheduler, and controller manager). The
remaining nodes are *workers* (run your application containers).

In our case, `kind` creates a single-node cluster where the control plane and
worker roles run on the same machine (a Docker container). In production this
would be 3+ nodes on cloud VMs.

### Namespace

A namespace is a virtual partition within a cluster. Think of it as a folder
that groups related resources together. Resources in one namespace can't
accidentally conflict with resources in another.

We use two namespaces:
- `timer` — all timer-2.0 application resources (backend, frontend, postgres)
- `logging` — Loki, Promtail, Grafana (kept separate because these are
  infrastructure tools, not part of the app itself)

The `default` and `kube-system` namespaces already exist in every cluster and
hold Kubernetes's own internal resources.

### Pod

A pod is the smallest deployable unit in Kubernetes. It contains one or more
containers that share a network namespace (they can reach each other on
`localhost`) and are always scheduled on the same node.

In almost all real-world cases, a pod contains exactly one container. The
multi-container pattern is used for *sidecars* (a logging agent running
alongside the main app) — but we don't use that here.

A pod on its own is fragile — if it dies, it's gone. Pods are almost never
created directly; instead you use a Deployment (below) which manages pods for
you.

### Deployment

A Deployment is a Kubernetes resource that tells the cluster "I want N copies
of this pod always running." It:

- Creates the pods
- Watches them; if one dies, it creates a replacement
- Handles rolling updates when you change the container image or config
- Keeps the history of previous versions so you can roll back

In Docker Compose terms, a Deployment is roughly the `backend:` or `frontend:`
service block, but with automatic recovery and rolling updates added.

### StatefulSet

A StatefulSet is like a Deployment but for stateful applications — specifically
databases. The key differences from a Deployment:

- **Stable pod names.** Pods are named `postgres-0`, `postgres-1`, etc. rather
  than random hashes. The database URL `postgres://...@postgres-0:5432/...` is
  always valid.
- **Stable storage.** Each pod gets its own PersistentVolumeClaim (see below)
  that follows it if the pod is rescheduled to a different node.
- **Ordered startup/shutdown.** Pods are started in order (0, then 1, then 2)
  which matters for database replication setup.

For timer-2.0 we run a single Postgres replica (no replication), so most of
these properties don't come into play — but using a StatefulSet is the correct
pattern for a database even when running solo.

### PersistentVolume and PersistentVolumeClaim

Docker Compose uses named volumes (`postgres_data:`) to store database data
outside the container. Kubernetes has an equivalent but more explicit system.

A **PersistentVolume (PV)** is a piece of storage provisioned in the cluster —
a directory on a node's disk, an NFS share, an AWS EBS volume, etc.

A **PersistentVolumeClaim (PVC)** is a request for storage: "give me 10 Gi of
ReadWriteOnce storage." Kubernetes finds or creates a PV that satisfies the
claim and binds them together.

In kind (local), PVCs are satisfied automatically by `hostPath` volumes (a
directory on the kind node's filesystem). In production on a cloud provider,
PVCs dynamically provision cloud block storage (EBS on AWS, Persistent Disk on
GCP).

The `volumeClaimTemplates` field in a StatefulSet is a shorthand: Kubernetes
creates one PVC per pod replica automatically, names it
`postgres-data-postgres-0`, and mounts it into the pod.

### Service

In Docker Compose, containers in the same network reach each other by service
name: the backend reaches the database at `db:5432` because Docker resolves the
service name to the container's IP.

In Kubernetes, pod IPs change every time a pod is restarted or rescheduled. A
**Service** is a stable, named network endpoint that sits in front of a set of
pods (selected by labels) and load-balances traffic across them.

When you create a Service named `backend` in the `timer` namespace, Kubernetes's
internal DNS makes it reachable at:
- `backend` (short name, within the same namespace)
- `backend.timer` (across namespaces)
- `backend.timer.svc.cluster.local` (fully qualified)

This is why the existing `nginx.conf` in the frontend image — which proxies to
`http://backend:8000` — works in Kubernetes without modification. The cluster
DNS resolves `backend` to the backend Service's ClusterIP, just like Docker
Compose resolves it to the backend container.

Three Service types:
- **ClusterIP** (default) — only reachable inside the cluster. Used for
  postgres and backend (they should never be directly exposed).
- **NodePort** — exposes the service on a port on every cluster node. Useful
  for debugging.
- **LoadBalancer** — provisions a cloud load balancer (AWS ELB, GCP LB) with
  a public IP. Used by nginx-ingress-controller in production.

### ConfigMap

A ConfigMap stores non-sensitive configuration as key-value pairs and makes it
available to pods as environment variables or mounted files.

For timer-2.0:
```yaml
data:
  DEBUG: "False"
  LOG_LEVEL: "INFO"
  ALLOWED_HOSTS: "timer.example.com,localhost"
```

These map directly to the environment variables that `settings.py` reads via
`django-environ`. Changing a ConfigMap value and restarting the pods is the
single dial for changing non-sensitive config — no image rebuild needed.

### Secret

A Secret is like a ConfigMap but for sensitive data: database passwords, API
keys, Django's `SECRET_KEY`. Kubernetes encodes Secret values in base64 (this
is NOT encryption — it's just encoding) and stores them in etcd, the cluster's
key-value database.

Important: in a real production environment, raw Kubernetes Secrets are not
considered secure because anyone with cluster access can read them. Production
systems add a layer on top — HashiCorp Vault, AWS Secrets Manager, or
Kubernetes's own Sealed Secrets. For this milestone we use plain Secrets
(appropriate for a learning deployment) and document the production path.

The `secret.example.yaml` file is checked into git with placeholder values.
The real `secret.yaml` is listed in `.gitignore` and never committed.

### Job

A Job runs a pod to completion rather than keeping it running forever. Kubernetes
retries the pod if it fails and considers the Job complete when the pod exits
successfully (exit code 0).

We use a Job for `python manage.py migrate`. The migration must run once and
succeed before the backend Deployment starts serving traffic. A Job is the
right tool because:
- It has a clear success/failure concept (unlike a Deployment, which just tries
  to keep pods alive)
- `kubectl wait --for=condition=complete job/timer-migrate` blocks the apply
  script until migrations are done
- It's visible in `kubectl get jobs` so you can check its status

### HorizontalPodAutoscaler (HPA)

An HPA watches a Deployment's CPU or memory usage and scales the number of
replicas up or down automatically.

For the backend:
```yaml
minReplicas: 2   # always at least 2 for redundancy
maxReplicas: 6   # never more than 6 (cost cap)
target: 70% CPU  # add a replica when average CPU across all backend pods > 70%
```

The HPA requires the *metrics-server* to be installed in the cluster —
metrics-server collects CPU/memory usage from each pod and exposes it via the
Kubernetes metrics API. kind does not include metrics-server by default, so the
setup script installs it.

### Liveness and Readiness Probes

These are health checks that Kubernetes runs against each pod:

**Readiness probe:** "Is this pod ready to receive traffic?" Kubernetes only
sends traffic to a pod after its readiness probe passes. For the backend we
probe `GET /health/` — once Django has started and connected to the database,
it returns 200 and traffic begins flowing. During a rolling update, the new pod
receives traffic only after it passes; the old pod keeps serving until then.

**Liveness probe:** "Is this pod still alive and functioning?" If the liveness
probe fails repeatedly (e.g. Django is stuck in a deadlock), Kubernetes kills
and restarts the pod. The same `GET /health/` endpoint serves both purposes.

---

## kubectl

`kubectl` is the command-line tool for interacting with a Kubernetes cluster.
It communicates with the cluster's API server over HTTPS.

```bash
kubectl apply -f k8s/namespace.yaml   # create/update a resource
kubectl get pods -n timer             # list pods in the timer namespace
kubectl logs -n timer deployment/backend   # stream logs
kubectl describe pod -n timer backend-abc  # detailed pod info (useful for debugging)
kubectl exec -it -n timer backend-abc -- bash  # shell into a pod (like docker exec)
```

`kubectl` reads cluster connection details (API server URL, TLS certificate,
credentials) from `~/.kube/config`. `kind create cluster` writes to this file
automatically, so after setup `kubectl` points at the local kind cluster.

---

## kind (Kubernetes IN Docker)

kind creates a Kubernetes cluster entirely inside Docker containers. Each
"node" in the cluster is a Docker container running a minimal Linux OS with
the Kubernetes control plane components installed.

Why kind instead of other local Kubernetes options:
- **Minikube** spins up a full VM (or uses Docker); heavier and slower to
  start than kind
- **k3s/k3d** is lighter but diverges from upstream Kubernetes in ways that
  can cause subtle differences
- **Docker Desktop Kubernetes** only exists on Mac and Windows; on WSL2 there
  is no Docker Desktop
- **kind** runs on any system with Docker, creates a cluster in ~30 seconds,
  and uses standard upstream Kubernetes — what works in kind works in GKE/EKS

The `kind-config.yaml` includes `extraPortMappings` to forward ports 80 and
443 from the host (WSL2) into the kind container. This is how the browser
reaches the nginx-ingress-controller inside the cluster.

---

## Helm

Helm is a package manager for Kubernetes. Instead of writing hundreds of lines
of Kubernetes YAML for a complex tool like Grafana (which needs a Deployment,
Service, ConfigMap, ServiceAccount, RBAC rules, PVC, etc.), Helm packages all
of that into a reusable *chart* maintained by the tool's developers.

You install a chart with one command:
```bash
helm install grafana grafana/grafana --namespace logging --values grafana-values.yaml
```

The `values.yaml` file is your customization layer — you only write the parts
that differ from the chart's defaults (datasource URLs, dashboard files,
storage size). Everything else is handled by the chart.

**When we use Helm vs raw YAML:**
- **Raw YAML (`k8s/`):** timer-2.0's own resources — backend, frontend, postgres,
  ingress. We write these ourselves so we understand exactly what exists and can
  modify anything without a chart abstraction in the way.
- **Helm:** Third-party tools — ingress-nginx, cert-manager, Loki, Promtail,
  Grafana. These are complex, actively maintained projects; using their official
  charts means we get production-tested configuration and security defaults.

---

## nginx-ingress-controller

In Kubernetes, an **Ingress resource** is just a set of routing rules written
in YAML:

```yaml
# Route all traffic to the frontend service
- host: timer.example.com
  http:
    paths:
    - path: /
      backend:
        service:
          name: frontend
          port: 80
```

But an Ingress resource by itself does nothing — it needs an **Ingress
controller** to read those rules and actually handle the traffic. The most
widely used controller is nginx-ingress, which runs an nginx instance inside
the cluster, watches Ingress resources, and dynamically generates an nginx
config from them.

Traffic flow with the Ingress controller:
```
Browser → kind port 80 → nginx-ingress-controller pod
       → (matches Ingress rules) → frontend Service ClusterIP
       → frontend pod (nginx) → serves static files / proxies /api/ to backend
```

The Ingress controller is the single point where TLS terminates: the browser
connects over HTTPS, the controller decrypts, and all traffic inside the
cluster is plain HTTP. This is called TLS termination at the edge.

---

## cert-manager + Let's Encrypt

Managing TLS certificates manually (generating CSRs, downloading certs,
configuring nginx, renewing before expiry) is tedious and error-prone.
cert-manager automates the entire lifecycle.

**What cert-manager does:**
1. Watches Ingress resources for a `cert-manager.io/cluster-issuer` annotation
2. When it sees one, it requests a certificate from the configured CA
3. Stores the cert and private key as a Kubernetes Secret
4. Configures the Ingress to use that Secret for TLS
5. Automatically renews the cert before it expires (Let's Encrypt certs last
   90 days; cert-manager renews at 60 days)

**ClusterIssuer:**
A ClusterIssuer tells cert-manager *how* to get certificates. Two are relevant:

`clusterissuer-selfsigned.yaml` — issues self-signed certificates. No internet
connection needed. The browser will show a security warning, but TLS encryption
still works. Used for local kind testing where there's no real domain.

`clusterissuer-letsencrypt.yaml` — issues free, publicly trusted certificates
from Let's Encrypt via the ACME HTTP-01 challenge. Let's Encrypt's servers
make an HTTP request to `http://yourdomain.com/.well-known/acme-challenge/...`
to prove you control the domain. Requires:
- A real public domain (e.g. `timer.yourhospital.com`)
- The cluster to be reachable from the public internet on port 80
- DNS pointing to the cluster's load balancer IP

For kind on a local machine, only the self-signed issuer works. The
Let's Encrypt issuer is documented for when this runs in production.

---

## Loki

Loki is a log aggregation system built by Grafana Labs. Its job is to receive
logs from all pods in the cluster, index them, store them, and make them
queryable.

**Why not the ELK stack (Elasticsearch + Logstash + Kibana)?**

ELK is the traditional log aggregation choice but it is expensive:
Elasticsearch indexes every word of every log line (full-text search), which
requires significant CPU and RAM — easily 4-8 GB just for Elasticsearch.

Loki takes a different approach: it stores log *labels* in an index (small and
fast) and the raw log text in compressed chunks (cheap storage). You query
logs by label (`{app="backend", namespace="timer"}`) and then filter within the
results using a query language called LogQL. For most operational use cases —
"show me all error logs from the backend in the last hour" — this is exactly
as useful as full-text search and costs a fraction of the compute.

For timer-2.0, the logs are already structured JSON (established in M1). Loki
can parse JSON fields and use them as labels or filter values. A LogQL query
like:
```
{app="backend", namespace="timer"} | json | logger="timer.audit" | level="INFO"
```
returns all audit log lines from the backend pods, filtered to INFO level.

---

## Promtail

Loki stores logs, but something needs to collect them from the pods and ship
them there. That's Promtail.

Promtail runs as a **DaemonSet** — one pod per node in the cluster. It:
1. Watches `/var/log/pods/` on the node for new log files (Kubernetes writes
   each container's stdout to a file here)
2. Tails those files in real time
3. Parses the Docker/Kubernetes metadata (pod name, namespace, container name)
   into labels
4. Optionally parses structured fields from the log body (we configure it to
   parse `level` and `logger` from our JSON logs)
5. Batches and ships log entries to Loki

Because Kubernetes writes all pod stdout/stderr to the node's filesystem, a
single Promtail pod on each node can collect logs from *all* containers on that
node without any code changes to the application. The Django backend just logs
to stdout (which it already does) and Promtail handles the rest.

---

## Grafana

Grafana is the visualization layer. It connects to data sources (Loki, in our
case) and lets you build dashboards — graphs, tables, log panels — by writing
queries.

**Provisioning:** Rather than clicking through the Grafana UI to configure a
datasource and create dashboards, we provision them declaratively:
- A `datasources.yaml` file in the Grafana Helm values tells it to add Loki as
  a datasource on startup
- Dashboard JSON files (exported from Grafana's UI) are mounted via a ConfigMap
  and loaded automatically

This means the Grafana setup is reproducible — deleting and reinstalling the
Helm release restores everything exactly.

**Two dashboards for timer-2.0:**

*Audit dashboard* — queries the `timer.audit` log stream and shows:
- Login success/failure counts over time (bar chart)
- Failed login attempts by username (table — useful for spotting brute force)
- Operation create/complete events over time

*API requests dashboard* — queries the `timer.api` log stream and shows:
- Request rate (requests per minute)
- Error rate (responses with status ≥ 400)
- Slowest requests (sorted by `duration_ms`)
- Status code distribution (pie chart)

---

## How everything connects — architecture diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  WSL2 host (or cloud VM)                                        │
│                                                                 │
│  Browser ──── port 80/443 ──────────────────────────────────┐  │
│                                                              │  │
│  ┌───────────────────────────────────────────────────────┐  │  │
│  │  kind cluster (single Docker container on WSL2)       │  │  │
│  │                                                       │  │  │
│  │  ┌────────────────────────────────────────────────┐  │  │  │
│  │  │  namespace: timer                              │  │  │  │
│  │  │                                                │  │  │  │
│  │  │  Ingress ◄───────────────────────────────────┘  │  │  │
│  │  │     │ routes all to frontend:80                  │  │  │
│  │  │     ▼                                            │  │  │
│  │  │  frontend Service ──► frontend Pod               │  │  │
│  │  │                         (nginx)                  │  │  │
│  │  │                           │                      │  │  │
│  │  │              /api/,/admin/│                      │  │  │
│  │  │                           ▼                      │  │  │
│  │  │  backend Service ──► backend Pods (×2-6)         │  │  │
│  │  │                         (Django/Gunicorn)        │  │  │
│  │  │                           │                      │  │  │
│  │  │                           ▼                      │  │  │
│  │  │  postgres Service ──► postgres-0 Pod             │  │  │
│  │  │                         (PostgreSQL)             │  │  │
│  │  │                           │                      │  │  │
│  │  │                           ▼                      │  │  │
│  │  │                     PVC (10 Gi disk)             │  │  │
│  │  │                                                  │  │  │
│  │  │  HPA ──watches──► backend Deployment             │  │  │
│  │  │  (scales 2-6 on CPU)                             │  │  │
│  │  │                                                  │  │  │
│  │  │  cert-manager ──watches──► Ingress TLS annot.   │  │  │
│  │  │       └──requests cert from Let's Encrypt        │  │  │
│  │  │       └──stores in Secret ──► Ingress uses it    │  │  │
│  │  └────────────────────────────────────────────────┘  │  │  │
│  │                                                       │  │  │
│  │  ┌────────────────────────────────────────────────┐  │  │  │
│  │  │  namespace: logging                            │  │  │  │
│  │  │                                                │  │  │  │
│  │  │  Promtail (DaemonSet)                          │  │  │  │
│  │  │    reads /var/log/pods/* (all pod stdout)      │  │  │  │
│  │  │    parses JSON fields (level, logger, etc.)    │  │  │  │
│  │  │    ships to Loki                               │  │  │  │
│  │  │         │                                      │  │  │  │
│  │  │         ▼                                      │  │  │  │
│  │  │  Loki (stores + indexes logs)                  │  │  │  │
│  │  │         │                                      │  │  │  │
│  │  │         ▼                                      │  │  │  │
│  │  │  Grafana (dashboards via kubectl port-forward) │  │  │  │
│  │  └────────────────────────────────────────────────┘  │  │  │
│  └───────────────────────────────────────────────────────┘  │  │
└─────────────────────────────────────────────────────────────────┘
```

**Key data flows:**

1. *Request path:* Browser → kind port 80 → nginx-ingress-controller →
   frontend Service → frontend Pod (nginx) → `/api/*` proxied to backend
   Service → one of 2-6 backend Pods → postgres Service → postgres-0 Pod

2. *Log path:* backend Pod writes JSON to stdout → Kubernetes writes to
   `/var/log/pods/` on the node → Promtail tails the file → ships to Loki →
   Grafana queries and displays

3. *Scaling path:* metrics-server scrapes CPU from backend Pods → HPA reads
   metrics → if average CPU > 70%, HPA increments `backend` Deployment
   replicas → new Pod starts → passes readiness probe → enters Service rotation

4. *TLS path (production):* cert-manager sees the Ingress `cluster-issuer`
   annotation → sends ACME challenge to Let's Encrypt → receives certificate →
   stores as Secret → nginx-ingress-controller mounts Secret → terminates TLS

---

## Why this architecture for an ASC timer?

An ambulatory surgery center operates on a schedule: procedures happen during
business hours, often in parallel across multiple ORs. Traffic is bursty (all
ORs active at 8 AM, quiet at 6 PM) and the consequence of downtime is real
(timing data lost mid-procedure).

The K8s architecture addresses this directly:
- **2 backend replicas minimum:** if one pod dies mid-procedure, the other
  continues serving without interruption
- **HPA:** if multiple ORs start procedures simultaneously, the backend scales
  out automatically; when they finish and data drops, it scales back in
- **Rolling updates:** new software versions deploy without taking down the
  app, so an update can happen during off-hours without a maintenance window
- **Loki/Grafana:** the audit log stream gives administrators visibility into
  who logged in, when operations were created, and what the API response times
  look like — important for a system handling clinical data
