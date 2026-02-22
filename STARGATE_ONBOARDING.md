# Exoscale Deploy Kit — StarGate Onboarding Guide

**Repository:** `https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit`  
**Last updated:** 2026-02-22  

This guide covers everything StarGate needs to clone, configure, and run the Exoscale Deploy Kit for their own project.

---

## What the kit does

A single `python3 deploy_pipeline.py` command executes a 7-stage deployment pipeline:

| Stage | What happens | Duration |
|-------|-------------|----------|
| 1. Docker Build | Multi-stage `linux/amd64` image built from `service/` | 1-3 min |
| 2. Docker Push | Versioned + `latest` tags pushed to Docker Hub | 1-2 min |
| 3. Exoscale Infrastructure | Security Group + SKS cluster + Node Pool | 5-8 min |
| 4. Wait for Nodes | Polls until all worker nodes are `Ready` | 3-8 min |
| 5. Kubernetes Manifests | Namespace, Deployment, Service, HPA, NetworkPolicy applied | <1 min |
| 6. Verify | Polls until pods reach `Running` state | 1-3 min |
| 7. Report | JSON report written to `outputs/` | instant |

**Total: ~15-25 minutes** for a fresh cluster with running pods.

---

## Step 1 — Access the repository

The repository is **private**. You need one of the following:

**Option A — GitHub Personal Access Token (easiest):**

Ask the repo owner to either:
- Add your GitHub username as a collaborator at: `https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit/settings/access`
- Or generate a read-only PAT for you

Then clone:
```bash
git clone https://YOUR_GITHUB_TOKEN@github.com/The-Synergy-Group-AG/exoscale-deploy-kit.git
cd exoscale-deploy-kit
```

**Option B — SSH (if your SSH key is authorized on the org):**
```bash
git clone git@github.com:The-Synergy-Group-AG/exoscale-deploy-kit.git
cd exoscale-deploy-kit
```

---

## Step 2 — Prerequisites

Before running the kit, ensure the following are installed and working:

```
Python 3.11+        →  python3 --version
pip                 →  pip --version
Docker (running)    →  docker info
kubectl             →  kubectl version --client
```

Install the kit's Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Step 3 — Credentials (.env file)

Copy the credentials template and fill it in:

```bash
cp .env.example .env
```

Edit `.env` with a text editor:

```ini
# ── Exoscale API Credentials ──────────────────────────────────
# Obtain at: https://portal.exoscale.com → IAM → API Keys → + Create
# Required roles: compute + network (or Unrestricted)
EXO_API_KEY=EXOxxxxxxxxxxxxxxxxxxxx
EXO_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Docker Hub Credentials ────────────────────────────────────
# Obtain at: https://hub.docker.com → Account Settings → Personal Access Tokens
# Permissions needed: Read, Write, Delete
DOCKER_HUB_TOKEN=dckr_pat_xxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ **Never commit `.env` to git.** It is already listed in `.gitignore`.

---

## Step 4 — Adapt the kit to your project

### 4a. Put your application in `service/`

The `service/` directory contains the application that gets built and deployed:

```
service/
  Dockerfile          ← your Dockerfile (multi-stage, linux/amd64, non-root user)
  requirements.txt    ← your app dependencies
  app.py              ← your app entrypoint (or whatever your app needs)
```

Replace the contents of `service/` with your own application code.
Keep the Dockerfile as `linux/amd64` and use a non-root user for Kubernetes compatibility.

### 4b. Configure the deployment wizard

When you run `python3 deploy_pipeline.py` for the first time, an interactive wizard collects:

| Setting | Example | Notes |
|---------|---------|-------|
| Project name | `stargate-prod` | Lowercase, used as prefix for all Exoscale resources |
| Exoscale zone | `ch-dk-2` | See https://portal.exoscale.com for your zone |
| Docker Hub username | `myorg` | The account where your image will be pushed |
| Service name | `stargate-api` | Used as the Docker image name |
| Service version | `1.0.0` | Becomes the image tag |
| Node count | `2` | Number of Kubernetes worker nodes |
| Node type | `standard / small` | Instance size (minimum: `small` for SKS) |

Settings are saved to `config.yaml` — you can edit it directly for subsequent runs.

---

## Step 5 — Run the deployment

### Interactive mode (first time — runs the wizard):
```bash
python3 deploy_pipeline.py
```

### Non-interactive mode (CI/CD — uses existing config.yaml):
```bash
python3 deploy_pipeline.py --auto
```

### Preflight check (validate credentials + config before deploying):
```bash
python3 preflight_check.py
```

---

## Step 6 — Access your deployment

After the pipeline completes:

- **Kubeconfig:** `outputs/{timestamp}/kubeconfig.yaml`
- **Deployment report:** `outputs/{timestamp}/deployment_report.json`
- **Access your service:** The Exoscale cloud controller auto-creates a Network Load Balancer. Its public IP appears as `EXTERNAL-IP` in:
  ```bash
  KUBECONFIG=outputs/{timestamp}/kubeconfig.yaml kubectl get svc -n {namespace}
  ```

---

## Step 7 — Teardown

When done, delete all Exoscale resources (cluster, node pool, security group):

```bash
python3 teardown.py              # interactive — shows what will be deleted, prompts y/N
python3 teardown.py --dry-run    # preview only — no deletions
python3 teardown.py --force      # no prompts — deletes immediately
```

Also clean up the local Docker images:
```bash
docker rmi {dockerhub_user}/{service_name}:{version}
docker rmi {dockerhub_user}/{service_name}:latest
```

---

## File structure overview

```
exoscale-deploy-kit/
├── deploy_pipeline.py      ← Main entry point — runs the full 7-stage pipeline
├── teardown.py             ← Deletes all project resources from Exoscale
├── wizard.py               ← Interactive setup wizard (auto-runs on first deploy)
├── preflight_check.py      ← Validates config + credentials before deploying
├── config_loader.py        ← Loads config.yaml + .env into one cfg dict
├── k8s_manifest_generator.py ← Generates K8s YAML from config
├── config.yaml             ← Project settings (edit this or use wizard)
├── .env.example            ← Credentials template (copy to .env and fill in)
├── requirements.txt        ← Python dependencies
├── service/                ← YOUR APPLICATION goes here
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
└── outputs/                ← Auto-generated per deployment (gitignored)
    └── {timestamp}/
        ├── kubeconfig.yaml
        ├── deployment_report.json
        └── k8s-manifests/
```

---

## Critical known limitations (do not repeat these mistakes)

1. **Exoscale zone matters:** API calls must use the zone-specific endpoint — the SDK handles this automatically when you set `zone=` correctly in `config.yaml`.
2. **Node size minimum:** SKS rejects `tiny` and `micro` instances. Use `small` or larger. The wizard enforces this automatically.
3. **Project name must be lowercase:** Exoscale resource names are DNS-label format. Use `stargate-prod` not `StarGate-Prod`. The wizard warns if you use mixed case.
4. **Never create the NLB manually:** Exoscale auto-creates it when a `type: LoadBalancer` service is applied via kubectl. A manually created NLB will conflict.
5. **NodePort range:** Port `30671` is pre-approved in the Exoscale default security group. Use this or `30888`/`30999`. Arbitrary NodePorts will be blocked.

---

## Support

Repository: `https://github.com/The-Synergy-Group-AG/exoscale-deploy-kit`  
Contact: The Synergy Group AG development team
