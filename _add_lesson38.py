#!/usr/bin/env python3
"""
Lesson 38: Dashboard queries, KSM triplication, and deployment health summary
"""
import subprocess
from pathlib import Path

PLAN_DIR = Path("/home/iandre/projects/jtp-bio-v3/docs/plans/125-True-Microservices-Deployment")

lesson38 = """
## Lesson 38 — Dashboard Fixes: KSM Triplication, Stale Zone Labels, Pod Count Queries (2026-03-05)

### Context
During Run 4 post-deployment monitoring (20260305_125730), the Grafana dashboard showed
multiple incorrect or missing values. Systematic debugging revealed 5 distinct issues.

---

### Issue 1: KSM Triplication (3x all metrics)

**Symptom:** Dashboard showed 660 services, 711 running pods, 9 nodes — all 3x actual values.

**Root Cause:** `prometheus.yml` had 3 scrape targets for kube-state-metrics (one per node IP
via NodePort). KSM is a **single pod** — NodePort routes all 3 IPs to the same pod. Scraping all
3 produces 3 identical sets of metrics with different `instance=` labels.

**Fix:** Reduce to 1 KSM target in `prometheus.yml`:
```yaml
# jtp-kube-state-metrics job — ONLY ONE TARGET
- targets:
    - '151.145.203.247:30808'
    # NOT: '91.92.142.14:30808', '151.145.200.72:30808'
    # NodePort routes all IPs to same pod — 3 targets = 3x triplication!
```

**Rule:** For any singleton K8s workload (KSM, single Prometheus, single Grafana) exposed via
NodePort, scrape ONLY ONE node IP — any node will route to the same pod.

---

### Issue 2: Pod Count Queries Using count() Instead of sum()

**Symptom:** "Pods Running" showed 237 (= total pods), "Pods NOT Ready" showed 711 (= 237 × 3 phases).

**Root Cause:** kube-state-metrics v2 emits one series **per pod per phase** for `kube_pod_status_phase`.
`count()` counts SERIES (always = total pod count). `sum()` sums VALUES (= pods actually in that phase).

**Before (wrong):**
```promql
count(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Running"})
→ Returns 237 (total pod count, NOT running count)
```

**After (correct):**
```promql
sum(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Running"})
→ Returns 79 (actual running pods)
```

**Rule:** For `kube_pod_status_phase`, always use `sum()` not `count()`.

---

### Issue 3: Cluster Zone Panel — No Data

**Symptom:** "Cluster Zone" panel showed "No data".

**Root Cause:** The query used `kube_node_labels{label_topology_kubernetes_io_zone=~".+"}` which
requires Exoscale K8s nodes to have the `topology.kubernetes.io/zone` label. Exoscale SKS nodes
do NOT have this label in their K8s metadata. `kube_node_labels` was 0 series as a result.

**Fix:** Changed query to use `kube_node_info` which always has 1 series per node, confirming
cluster connectivity even without zone label. The zone is `ch-dk-2` (encoded in the Exoscale
API endpoint URL: `aafd8278-...-sks-ch-dk-2.exo.io`).

**Rule:** Don't rely on `topology.kubernetes.io/zone` label for Exoscale SKS clusters.
Use the Exoscale API URL or static configuration to determine zone.

---

### Issue 4: Namespace Panel — No Data

**Symptom:** "Namespace" panel showed "No data".

**Root Cause:** `kube_namespace_labels{namespace="exo-jtp-prod"}` only emits series if the
namespace HAS at least one label. Fresh namespaces created without labels produce no series.
`kube_namespace_info` always emits 1 series per namespace regardless of labels.

**Fix:** Changed query from `kube_namespace_labels` → `kube_namespace_info`.

**Rule:** For namespace existence checks, always use `kube_namespace_info{namespace="..."}`.
`kube_namespace_labels` is unreliable for unlabelled namespaces.

---

### Issue 5: Memory Limit < Request in 80 Service Manifests

**Symptom:** 9 deployments showing "Not Available" (DEPLOY FAILED state).

**Root Cause:** `gen_service_manifests.py` generated manifests with:
```yaml
resources:
  requests:
    memory: "128Mi"   # Scheduler uses this for node placement
  limits:
    memory: "64Mi"    # WRONG: limit < request
```
Kubernetes k8s 1.35+ kubelet rejects containers where `limits.memory < requests.memory`
with `CreateContainerConfigError`. 80 of 219 service manifests had this bug.

**Additional finding:** `docker-jtp-hpa` has `minReplicas: 2` requiring 2 gateway pods.
With `maxUnavailable: 0, maxSurge: 1`, this causes the deployment to be "unavailable"
if the second pod cannot start (image pull rate limits, resource constraints, etc.).

**Fix:** In `gen_service_manifests.py`, enforce `limits.memory >= requests.memory`:
```python
# Correct resource spec (64Mi request, 128Mi limit)
resources:
  requests:
    cpu: "10m"
    memory: "64Mi"   # Lower request = easier to schedule
  limits:
    cpu: "500m"
    memory: "128Mi"  # Higher limit = more room to grow
```

**Rule:** Memory limits MUST be >= memory requests. If a service needs 128Mi, set:
  `requests.memory: 64Mi` (scheduling baseline) + `limits.memory: 128Mi` (hard cap).

---

### Post-Fix Dashboard State (Run 4, after Lesson 38 fixes)

| Panel | Before Fix | After Fix |
|-------|-----------|-----------|
| Total Services | 660 (3x) | **220** ✅ |
| Pods Running | 711 (3x) | **220** ✅ |
| Pods NOT Ready | 2,130 (3x × 3 phases) | **17** ✅ |
| Worker Nodes | 9 (3x) | **3** ✅ |
| Cluster Zone | No data | kube_node_info (3 nodes) ✅ |
| Namespace | No data | 1 ✅ |
| Deployment State | DEPLOY FAILED (fake) | DEPLOY FAILED (real — 9/220) |
| KSM Targets | 3 (triplication) | **1** ✅ |

The DEPLOY FAILED state is now **accurate** — 9 of 220 deployments are genuinely not
available due to `CreateContainerConfigError` from memory limit < request specs.

---

### kubeconfig TLS Note

The kubeconfig stored at `/home/iandre/.kube/config` connects to:
`https://aafd8278-05ea-4ff9-ad86-62a9d2146913.sks-ch-dk-2.exo.io:443`

The TLS certificate is issued for Traefik's internal name (not the Exoscale FQDN).
Use `--insecure-skip-tls-verify` for direct kubectl operations until the kubeconfig
is refreshed via `exo compute sks kubeconfig`.

---
"""

# Append to Phase 2 completion report
PHASE2 = PLAN_DIR / "PHASE_2_COMPLETION_REPORT.md"
content = PHASE2.read_text() if PHASE2.exists() else ""
if "Lesson 38" not in content:
    PHASE2.write_text(content + "\n\n---\n" + lesson38)
    print("[OK] Lesson 38 appended to PHASE_2_COMPLETION_REPORT.md")

# Also create standalone lesson file
L38 = PLAN_DIR / "LESSON_38_DASHBOARD_FIXES.md"
L38.write_text(f"# Lesson 38 — Dashboard Fixes\n{lesson38}")
print(f"[OK] Created {L38.name}")
