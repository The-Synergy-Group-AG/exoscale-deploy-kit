#!/usr/bin/env python3
"""
Add Lesson 36 to DEPLOYMENT_LESSONS_LEARNED.md
Lesson 36: Monitoring Continuity (kube-state-metrics + prometheus.yml node IPs)
"""
from pathlib import Path

doc_path = Path(__file__).parent.parent / "docs/plans/125-True-Microservices-Deployment/DEPLOYMENT_LESSONS_LEARNED.md"
content = doc_path.read_text()

LESSON_36 = """
---

### MONITORING CONTINUITY (Post-Deploy)

#### Lesson 36 — kube-state-metrics + prometheus.yml Must Be Re-synced After Every Cluster Deployment (CRITICAL)

**Problem discovered**: After Run 4 succeeded (210/210 services HEALTHY), both Grafana dashboards showed stale/no data:
- **JTP Deployment Dashboard**: "DEPLOY FAILED", Pods Running: 0  
- **Deployment Engine Dashboard**: K8s Manifests: 0

**Root causes (3 compounding issues):**

1. **kube-state-metrics not deployed to new cluster**: `run_deploy.sh` deploys 220 service pods but never installs `kube-state-metrics`. Without it, Prometheus has no `kube_pod_*`, `kube_deployment_*` metrics — all K8s-derived panels show 0/no data.

2. **prometheus.yml has hardcoded node IPs**: The `jtp-kube-state-metrics` scrape job targets static IPs from the *previous* cluster. Every new deployment creates new Exoscale VMs with different IPs. These old targets were all `DOWN`.

3. **Deployment engine exporter scans wrong/empty directory**: The exporter at `:8005` scans `engines/deployment_engine/outputs/manifests/` but Run 4 manifests were in `exoscale-deploy-kit/outputs/20260305_125732/k8s-manifests/`. Also: Python 3.12's `Path.rglob()` no longer follows symlinks by default — copying real files is required.

**Root design flaw**: The deployment pipeline was written to deploy infrastructure but NOT to update the monitoring/observability layer that tracks it. Every new cluster is invisible to Grafana until manual intervention.

**Rule**: After every successful deployment, `run_deploy.sh` MUST automatically:
1. Deploy `kube-state-metrics` to the new cluster (NodePort 30808)
2. Read new node ExternalIPs from kubeconfig → update `prometheus.yml` → restart Prometheus
3. Copy new run's manifests to `engines/deployment_engine/outputs/manifests/kubernetes/` → restart exporter

**Fixed in**: `run_deploy.sh` Step 2.6 → calls `_post_deploy_monitoring.sh` (Lesson 35 implementation)

**The fix pattern** (`_post_deploy_monitoring.sh`):
```bash
# Step 2.6a: Deploy kube-state-metrics to new cluster
helm upgrade --install kube-state-metrics prometheus-community/kube-state-metrics \\
  --namespace kube-system --kubeconfig="${KUBECONFIG_PATH}" \\
  --set service.type=NodePort --set service.nodePort=30808 \\
  --set resources.requests.cpu=10m --wait --timeout=120s

# Step 2.6b: Auto-update prometheus.yml with new node IPs
NODE_IPS=$(kubectl get nodes --kubeconfig="${KUBECONFIG_PATH}" \\
    -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="ExternalIP")].address}{"\\n"}{end}')
# Python regex replaces targets block + run_id label + restarts Prometheus container

# Step 2.6c: Sync manifests (real files, not symlinks — Python 3.12 rglob doesn't follow symlinks)
cp "$RUN_DIR/k8s-manifests/"*.yaml "$ENGINE_MANIFESTS/"
pkill -f metrics_exporter.py && nohup python3 engines/deployment_engine/inputs/metrics_exporter.py &
```

**Never again** (Quick Reference update): After a successful deploy, Grafana dashboards are automatically live within ~60s.

**Symptom checklist** (if dashboards still show stale data after a new deployment):
```bash
# Check 1: kube-state-metrics targets UP?
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json,sys; r=json.load(sys.stdin)
kube=[t for t in r['data']['activeTargets'] if 'kube' in t['labels'].get('job','')]
[print(t['scrapeUrl'], t['health']) for t in kube]"
# All should show 'up'. If 'down': old IPs in prometheus.yml or ksm not deployed.

# Check 2: prometheus.yml IPs match cluster?
kubectl get nodes --kubeconfig=<kubeconfig> -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="ExternalIP")].address}{"\\n"}{end}'
# Compare against IPs in prometheus.yml jtp-kube-state-metrics targets

# Fix: re-run monitoring sync
bash exoscale-deploy-kit/_post_deploy_monitoring.sh <kubeconfig> <run_ts> <outputs_dir>
```
"""

APPENDIX_ROW = "| 36 | 125-P2 | kube-state-metrics + prometheus.yml not auto-synced | Monitoring | ✅ |"

# Insert Lesson 36 before Part 2 (Swiss-Clock procedure)
PART2_ANCHOR = "\n## Part 2: Swiss-Clock Deployment Procedure"

QUICK_REF_OLD = "10. GRAFANA       = verify all 7 pipeline stages annotated before declaring success"
QUICK_REF_NEW = """10. GRAFANA       = verify all 7 pipeline stages annotated before declaring success
11. MONITORING    = Step 2.6 auto-deploys ksm + syncs prometheus.yml IPs after every deploy"""

APPENDIX_OLD = "| 35b | 125-P2 | maxUnavailable:0 deadlock | K8s | ✅ |"
APPENDIX_NEW = """| 35b | 125-P2 | maxUnavailable:0 deadlock | K8s | ✅ |
| 36  | 125-P2 | kube-state + prometheus.yml not synced on new cluster | Monitoring | ✅ |"""

EXEC_OLD = "we have identified **35 critical lessons**"
EXEC_NEW = "we have identified **36 critical lessons**"

updated = content
updated = updated.replace(EXEC_OLD, EXEC_NEW)
updated = updated.replace(PART2_ANCHOR, LESSON_36 + PART2_ANCHOR)
updated = updated.replace(QUICK_REF_OLD, QUICK_REF_NEW)
updated = updated.replace(APPENDIX_OLD, APPENDIX_NEW)

doc_path.write_text(updated)

# Verify
new_content = doc_path.read_text()
assert "Lesson 36" in new_content, "Lesson 36 not found"
assert "36 critical lessons" in new_content, "Executive summary not updated"
assert "11. MONITORING" in new_content, "Quick ref not updated"
print(f"[OK] DEPLOYMENT_LESSONS_LEARNED.md updated with Lesson 36")
print(f"     File size: {len(new_content):,} chars")
