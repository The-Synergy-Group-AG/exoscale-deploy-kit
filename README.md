# Exoscale Deploy Kit

> **Battle-tested Kubernetes deployment pipeline for Exoscale SKS.**
> Validated on live Exoscale infrastructure 2026-02-20. Drop it into any project, configure two files, and deploy.

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Platform | Exoscale SKS (Kubernetes) |
| Registry | Docker Hub |
| kubectl | any recent version |

---

## What This Kit Does

A single `python3 deploy_pipeline.py` command executes a 7-stage deployment:

| Stage | What happens | Typical duration |
|-------|-------------|-----------------|
| 1. Docker Build | Multi-stage `linux/amd64` image built from `service/` | 1-3 min |
| 2. Docker Push | Versioned + `latest` tags pushed to Docker Hub | 1-2 min |
| 3. Exoscale Infrastructure | Security Group + SKS cluster + Node Pool created | 5-8 min |
| 4. Wait for Nodes | Polls until all worker nodes are `Ready` | 3-8 min |
| 5. Kubernetes Manifests | Namespace, Deployment, Service, HPA, NetworkPolicy, ResourceQuota applied | <1 min |
| 6. Verify | Polls until pods reach `Running` state | 1-3 min |
| 7. Report | JSON deployment report written to `outputs/` | instant |

**Total: ~15-25 minutes** for a fresh cluster + running pods.

**What gets created in your Exoscale account:**
- 1 Security Group (`{project_name}-sg-HHMMSS`)
- 1 SKS Pro cluster (`{project_name}-cluster-HHMMSS`)
- 1 Node Pool with N worker nodes (`{project_name}-workers`)
- 1 Network Load Balancer (auto-created by Exoscale cloud controller)
- Kubernetes manifests in `outputs/{timestamp}/k8s-manifests/`
- Kubeconfig in `outputs/{timestamp}/kubeconfig.yaml`

---

## Prerequisites

Before running the kit, ensure you have:

```
- Python 3.11+
- pip install -r requirements.txt
- Docker (running — docker info should succeed)
- kubectl (installed, in PATH — kubectl version --client should succeed)
- Exoscale account with API keys (IAM → API Keys → Create)
- Docker Hub account with an access token (Account Settings → Security → Access Tokens)
```

### Exoscale API Key permissions required
Your API key needs the following IAM roles:
- `compute` — create/delete instances, SKS clusters, node pools
- `network` — create/delete security groups, load balancers

---

## Quick Start (5 steps)

### Step 1 — Configure credentials
```bash
cp .env.example .env
# Edit .env with your real credentials:
#   EXO_API_KEY=EXOxxxxxxxxxxxxxxxxxxxxxxx
#   EXO_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#   DOCKER_HUB_TOKEN=dckr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Step 2 — Configure the project
```bash
# Edit config.yaml — at minimum change:
#   project_name: my-project
#   service_name: my-service
#   docker_hub_user: yourdockerhubusername
#   exoscale_zone: ch-gva-2   (or ch-dk-2, de-fra-1, at-vie-1)
```

### Step 3 — Install Python dependencies
```bash
pip install -r requirements.txt
```

### Step 4 — Replace sample service (optional)
```bash
# The service/ directory contains a sample Flask app.
# To use your own application:
#   - Replace service/app.py with your code
#   - Update service/Dockerfile and service/requirements.txt
#   - Ensure your app exposes GET /health (returns HTTP 200)
#   - Set k8s_port in config.yaml to match your app's listen port
```

### Step 5 — Deploy
```bash
python3 deploy_pipeline.py
```

### Teardown (when done)
```bash
python3 teardown.py           # Interactive confirmation
python3 teardown.py --force   # No prompts
python3 teardown.py --dry-run # Preview only — no changes
```

---

## Configuration Reference

### `config.yaml` — Non-secret settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `project_name` | string | `my-project` | Used as prefix for all Exoscale resource names. Must be unique in your account. |
| `service_name` | string | `my-service` | Docker image name and Kubernetes deployment name |
| `service_version` | string | `1.0.0` | Docker image tag (versioned) |
| `docker_hub_user` | string | `myuser` | Docker Hub username (not the token — just the username) |
| `exoscale_zone` | string | `ch-gva-2` | Exoscale zone. Options: `ch-gva-2`, `ch-dk-2`, `de-fra-1`, `at-vie-1` |
| `node_count` | int | `2` | Number of worker nodes in the node pool |
| `node_disk_gb` | int | `50` | Disk size per worker node (GB) |
| `node_type_family` | string | `standard` | Instance family filter. `standard` = general-purpose |
| `node_type_size` | string | `medium` | Instance size filter. Options: `tiny`, `small`, `medium`, `large`, `extra-large` |
| `k8s_namespace` | string | `my-project-production` | Kubernetes namespace for all workloads |
| `k8s_replicas` | int | `2` | Number of pod replicas (also HPA minimum) |
| `k8s_port` | int | `5000` | Container port your app listens on |
| `k8s_service_port` | int | `5000` | Kubernetes Service port (usually same as k8s_port) |
| `k8s_nodeport` | int | `30671` | NodePort for direct access. **Must be pre-approved (see Lesson 7).** |
| `sks_cni` | string | `calico` | Kubernetes CNI plugin |
| `sks_level` | string | `pro` | SKS cluster tier (`starter` or `pro`) |
| `sks_addons` | list | `[exoscale-cloud-controller, metrics-server]` | SKS addons. `exoscale-cloud-controller` is required for NLB auto-provisioning. |

### `.env` — Credentials (never commit this file)

| Variable | Description |
|----------|-------------|
| `EXO_API_KEY` | Exoscale API key (starts with `EXO`) |
| `EXO_API_SECRET` | Exoscale API secret |
| `DOCKER_HUB_TOKEN` | Docker Hub personal access token (starts with `dckr_pat_`) |

---

## 12 Critical Lessons Learned

These lessons are the result of extensive live testing on Exoscale infrastructure.
Each one represents a failure mode that was discovered and resolved in production.

### 1. Zone-specific API endpoint (CRITICAL)

```
CORRECT: https://api-ch-gva-2.exoscale.com/v2
WRONG:   https://api.exoscale.com/v2  ← returns 404 on compute endpoints
```

The Exoscale v2 API uses zone-specific endpoints. `api.exoscale.com` returns 404 for
most compute, SKS, and network endpoints. Always use `api-{zone}.exoscale.com`.

**This kit:** The `exoscale` Python SDK handles this automatically when you pass `zone=` to `Client()`.

---

### 2. Use the official Python SDK — not manual HMAC

Manual HMAC-SHA256 signing of Exoscale API requests is error-prone and fails silently.
The `exoscale` SDK (v0.16.1+) handles authentication, request signing, retries, and
zone routing correctly.

```bash
pip install exoscale>=0.16.1
```

**This kit:** All API calls use `from exoscale.api.v2 import Client`.

---

### 3. Query instance type IDs at runtime — never hardcode them

Exoscale instance type UUIDs change across zones and platform updates. A hardcoded
instance type ID that works in `ch-gva-2` will fail in `de-fra-1`.

**This kit:** `c.list_instance_types()` is called at runtime, filtered by `node_type_family`
and `node_type_size` from `config.yaml`.

---

### 4. Node pool MUST be Ready before applying K8s manifests

Applying Kubernetes manifests while worker nodes are still booting results in pods
stuck in `Pending` state indefinitely. The scheduler cannot place pods on nodes
that have not yet joined the cluster.

**This kit:** Stage 4 polls `kubectl get nodes` every 20 seconds for up to 12 minutes,
waiting until `node_count` nodes are `Ready` before proceeding to Stage 5.

---

### 5. Create nodepool WITHOUT Security Group, then update (DEFINITIVE)

Adding a Security Group to a nodepool during `create_sks_nodepool()` on a fresh cluster
returns HTTP 500. This is a known Exoscale API behaviour.

**Correct two-step approach (always succeeds):**
```python
# Step A: Create without SG
c.create_sks_nodepool(id=cluster_id, name=pool_name, ...)  # no security_groups

# Step B: Update after pool is Running
c.update_sks_nodepool(id=cluster_id, sks_nodepool_id=pool_id,
                      security_groups=[{"id": sg_id}])
```

**This kit:** `deploy_pipeline.py` implements this two-step pattern automatically.

---

### 6. Never create the NLB manually

The `exoscale-cloud-controller` addon automatically provisions a Network Load Balancer
when a Kubernetes `Service` of `type: LoadBalancer` is applied. Creating an NLB manually
results in a duplicate NLB that must be manually deleted.

**This kit:** `k8s_manifest_generator.py` generates a `Service` with `type: LoadBalancer`
and the annotation `service.beta.kubernetes.io/exoscale-loadbalancer-name`. The NLB
appears as `EXTERNAL-IP` in `kubectl get svc` within a few minutes.

---

### 7. NodePort must be pre-approved in the default Security Group

Exoscale's default Security Group pre-approves specific NodePort ranges.
Using any other NodePort results in traffic being blocked with no error message.

**Pre-approved NodePorts (Exoscale default SG):** `30671`, `30888`, `30999`

**This kit:** `config.yaml` defaults to `k8s_nodeport: 30671`. Override with `--nodeport`
in `k8s_manifest_generator.py` if you have a custom SG rule for another port.

---

### 8. Docker build args must be a Python list

Using string interpolation in `subprocess.run()` for Docker build commands causes
argument parsing failures that are hard to debug.

```python
# CORRECT — args as list
subprocess.run(["docker", "build", "--platform", "linux/amd64", "--tag", image, "."])

# WRONG — string interpolation
subprocess.run(f"docker build --platform linux/amd64 --tag {image} .")
```

**This kit:** All subprocess calls use list arguments.

---

### 9. kubectl needs KUBECONFIG and PATH set explicitly

`subprocess.run()` on Linux does not inherit the shell's PATH or KUBECONFIG environment
variables. Always pass `env=` explicitly.

```python
env = {"KUBECONFIG": str(kc_path), "PATH": "/usr/local/bin:/usr/bin:/bin"}
subprocess.run(["kubectl", "get", "nodes"], env=env)
```

**This kit:** All kubectl calls in `deploy_pipeline.py` and `teardown.py` use explicit `env=`.

---

### 10. Worker nodes take 3-8 minutes after nodepool creation

`c.wait(op_id)` returning success means the **create operation** completed, not that
nodes are **Ready**. Nodes boot, pull container images, join the cluster, and pass
readiness checks over 3-8 minutes.

**This kit:** Stage 4 (`stage_wait_for_nodes()`) polls until all nodes are `Ready`,
with a 12-minute deadline before proceeding anyway.

---

### 11. Create Docker Hub pull secret before applying manifests

If your Docker Hub repository is private, pods will fail with `ErrImagePull` unless
a `docker-registry` secret is created in the namespace before the manifests are applied.

```bash
kubectl create secret docker-registry dockerhub-creds \
    --docker-server=docker.io \
    --docker-username=$DOCKER_USER \
    --docker-password=$DOCKER_TOKEN \
    -n $NAMESPACE
```

**This kit:** Stage 5 creates `dockerhub-creds` in the namespace before running
`kubectl apply`. Works for both private and public repos.

---

### 12. Use --dry-run=client -o yaml | kubectl apply -f - for secrets

This pattern is idempotent — it will create the secret if it does not exist, or
update it if it does. It avoids `AlreadyExists` errors on re-deployment and does
not leave credentials in shell history.

```python
r = subprocess.run(
    ["kubectl", "create", "secret", "docker-registry", "dockerhub-creds",
     "--dry-run=client", "-o", "yaml", ...],
    capture_output=True, text=True
)
subprocess.run(["kubectl", "apply", "-f", "-"], input=r.stdout, ...)
```

**This kit:** Stage 5 uses this pattern for the Docker Hub pull secret.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `HTTP 404` on any API call | Wrong zone or using `api.exoscale.com` | Set correct `exoscale_zone` in `config.yaml` |
| `HTTP 500` on nodepool creation | SG specified during creation on fresh cluster | Handled automatically (two-step pattern) |
| `ErrImagePull` on pods | Docker Hub pull secret missing or wrong credentials | Check `DOCKER_HUB_TOKEN` in `.env`; re-run pipeline |
| Pods stuck in `Pending` | Nodes not Ready yet | Wait longer; check `kubectl get nodes` |
| `SG deletion failed` | Cluster/NLB still holding SG lock | `teardown.py` retries automatically after 30s |
| NodePort not reachable from internet | Using non-approved NodePort | Change `k8s_nodeport` to `30671`, `30888`, or `30999` |
| `Module not found: exoscale` | SDK not installed | `pip install -r requirements.txt` |
| `No kubeconfig found` in teardown | No previous deployment in `outputs/` | Pass kubeconfig manually or skip K8s cleanup |
| `Cannot connect to Docker daemon` | Docker not running | `docker info` to check; start Docker |

---

## Cost Reference + Cleanup

### Estimated costs per deployment cycle (ch-gva-2, 2026)

| Resource | Cost |
|----------|------|
| SKS Pro cluster | ~CHF 0.10/hour |
| 2x standard.medium nodes | ~CHF 0.20/hour each |
| Network Load Balancer | ~CHF 0.05/hour |
| **Total** | **~CHF 0.55/hour** |

A full test cycle (deploy → verify → teardown) typically takes 30-60 minutes, costing ~CHF 0.30-0.55.

### Cleanup

```bash
# Full automated teardown (recommended)
python3 teardown.py --force

# Preview what will be deleted (no changes made)
python3 teardown.py --dry-run

# Remove local Docker images
docker rmi {docker_hub_user}/{service_name}:1.0.0
docker rmi {docker_hub_user}/{service_name}:latest

# Verify cleanup in Exoscale portal
# https://portal.exoscale.com -> Compute -> SKS, Load Balancers, Security Groups
# All {project_name}-* resources should be gone
```

### Outputs directory

Deployment artifacts are stored in `outputs/{timestamp}/`:

```
outputs/
└── 20260222_120000/
    ├── kubeconfig.yaml              ← Cluster access credentials (24h TTL)
    ├── deployment_report.json       ← Full deployment record
    └── k8s-manifests/
        ├── 00-namespace.yaml
        ├── 01-deployment.yaml
        ├── 02-service.yaml
        ├── 03-hpa.yaml
        ├── 04-network-policy.yaml
        └── 05-resource-quota.yaml
```

The `outputs/` directory is gitignored. Do not commit kubeconfig files.

---

## Kit Structure

```
exoscale-deploy-kit/
├── README.md                    ← This file
├── config.yaml                  ← Non-secret configuration (edit me)
├── .env.example                 ← Credential template (copy to .env, fill in, never commit)
├── .gitignore                   ← Excludes .env, outputs/, *.kubeconfig
├── requirements.txt             ← Python dependencies
│
├── deploy_pipeline.py           ← Main deployment script (7 stages)
├── teardown.py                  ← Full infrastructure teardown
├── k8s_manifest_generator.py    ← Kubernetes YAML generator
├── config_loader.py             ← Shared config loading utility
│
├── service/                     ← Sample Flask app (replace with your code)
│   ├── app.py                   ← Flask service (3 endpoints: /, /health, /api/v1/info)
│   ├── Dockerfile               ← Multi-stage build (non-root, gunicorn)
│   └── requirements.txt         ← Flask + gunicorn
│
└── outputs/                     ← Runtime output directory (gitignored)
    └── {timestamp}/
        ├── kubeconfig.yaml
        ├── deployment_report.json
        └── k8s-manifests/
```

---

## Supported Exoscale Zones

| Zone ID | Location |
|---------|----------|
| `ch-gva-2` | Geneva, Switzerland |
| `ch-dk-2` | Zurich, Switzerland |
| `de-fra-1` | Frankfurt, Germany |
| `at-vie-1` | Vienna, Austria |
| `bg-sof-1` | Sofia, Bulgaria |

Set `exoscale_zone` in `config.yaml` to any of the above.

---

---

## Using This Kit in Another Project

This kit is published as a standalone repository:
**[github.com/The-Synergy-Group-AG/exoscale-deploy-kit](https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit)**

### Option A — Clone as a standalone deploy directory

Use this when starting a new project from scratch.

```bash
git clone https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit.git my-project-deploy
cd my-project-deploy

cp .env.example .env
# Edit .env:       EXO_API_KEY, EXO_API_SECRET, DOCKER_HUB_TOKEN
# Edit config.yaml: project_name, service_name, docker_hub_user, exoscale_zone

pip install -r requirements.txt
python3 deploy_pipeline.py   # full deploy (~5-20 min)
python3 teardown.py --force  # clean teardown when done
```

### Option B — Embed into an existing repo as a git subtree

Use this when you want the kit to live inside your existing project repository
(e.g. at `deploy/`) and still receive upstream kit updates.

**Initial setup (one-time, run from your project root):**

```bash
git subtree add \
  --prefix=deploy \
  https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit.git \
  main --squash
git push
```

The full kit is now at `your-project/deploy/`. Use it immediately:

```bash
cd deploy/
cp .env.example .env
# Edit .env and config.yaml for your project
pip install -r requirements.txt
python3 deploy_pipeline.py
```

**Pulling future kit updates into your project:**

```bash
# Run from your project root:
git subtree pull \
  --prefix=deploy \
  https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit.git \
  main --squash
git push
```

### What to customise per project

| File | What to change |
|------|---------------|
| `.env` | `EXO_API_KEY`, `EXO_API_SECRET`, `DOCKER_HUB_TOKEN` — your credentials |
| `config.yaml` | `project_name`, `service_name`, `docker_hub_user`, `exoscale_zone` |
| `service/app.py` | Replace with your actual application code |
| `service/Dockerfile` | Adjust base image, port, startup command for your app |
| `service/requirements.txt` | Your app's Python dependencies |

`deploy_pipeline.py`, `teardown.py`, and `k8s_manifest_generator.py` work
out of the box with **zero modification** — all behaviour is controlled by `config.yaml`.


## License

MIT — free to use, modify, and distribute.

---

*Exoscale Deploy Kit — battle-tested Kubernetes deployment for Exoscale SKS.*
