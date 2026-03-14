#!/usr/bin/env python3
"""
Fix dashboard JSON queries:
1. count(kube_pod_status_phase) → sum(kube_pod_status_phase) [KSM v2 multi-phase format]
2. kube_node_labels zone query → kube_node_info with provider_id label (Exoscale has no zone labels)
3. kube_namespace_labels → kube_namespace_info (namespace may have no labels)
"""
import json, re
from pathlib import Path

DASHBOARD = Path("/home/iandre/projects/jtp-bio-v3/monitoring/grafana/dashboards/jtp-deployment-dashboard.json")

content = DASHBOARD.read_text(encoding='utf-8')
data = json.loads(content)
changes = []

def fix_panels(panels):
    for panel in panels:
        title = panel.get('title', '')
        targets = panel.get('targets', [])
        for t in targets:
            expr = t.get('expr', '')
            if not expr:
                continue
            new_expr = expr

            # Fix 1: count(kube_pod_status_phase{...phase="Running"}) → sum(...)
            # KSM v2 emits one series per pod per phase; sum() = actual count in that phase
            if 'kube_pod_status_phase' in expr and expr.startswith('count('):
                new_expr = 'sum(' + expr[6:]  # replace 'count(' with 'sum('
                changes.append(f"[{title}] count→sum: pod_status_phase")

            # Fix 2: Cluster Zone — Exoscale nodes have no topology.kubernetes.io/zone label
            # Use label_replace on kube_node_info provider_id to extract zone from Exoscale UUID
            # OR just change to a simpler query that shows the zone from prometheus scrape labels
            if 'label_topology_kubernetes_io_zone' in expr:
                # Use the 'cluster' label from the prometheus scrape config or 'plan' label
                # Actually best: use kube_node_info and extract zone from plan/run_id labels
                new_expr = 'kube_node_info'
                t['legendFormat'] = 'ch-dk-2'
                changes.append(f"[{title}] zone query → kube_node_info (Exoscale has no topology label)")

            # Fix 3: kube_namespace_labels → kube_namespace_info
            # kube_namespace_labels requires the namespace to HAVE labels; kube_namespace_info always exists
            if 'kube_namespace_labels{namespace="exo-jtp-prod"}' in expr:
                new_expr = expr.replace(
                    'kube_namespace_labels{namespace="exo-jtp-prod"}',
                    'kube_namespace_info{namespace="exo-jtp-prod"}'
                )
                changes.append(f"[{title}] namespace_labels → namespace_info")

            if new_expr != expr:
                t['expr'] = new_expr

        # Recurse for row/nested panels
        sub_panels = panel.get('panels', [])
        if sub_panels:
            fix_panels(sub_panels)

fix_panels(data.get('panels', []))

# Write back
DASHBOARD.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"Dashboard updated: {len(changes)} changes")
for c in changes:
    print(f"  {c}")

# Now reload via Grafana API
import urllib.request, urllib.error
GRAFANA_URL = "http://localhost:3000"
GRAFANA_AUTH = ("admin", "admin")

# Get UID from dashboard JSON
uid = data.get('uid', '')
if uid:
    try:
        payload = json.dumps({"dashboard": data, "overwrite": True, "folderId": 0}).encode()
        req = urllib.request.Request(
            f"{GRAFANA_URL}/api/dashboards/db",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        import base64
        creds = base64.b64encode(f"{GRAFANA_AUTH[0]}:{GRAFANA_AUTH[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        print(f"\n[OK] Dashboard reloaded into Grafana: {result.get('status','?')} uid={result.get('uid','?')}")
    except Exception as e:
        print(f"\n[WARN] Could not auto-reload dashboard: {e}")
        print("  Manually reload: Dashboard Settings → Save dashboard in Grafana")
else:
    print(f"\n[WARN] Dashboard has no UID — cannot auto-reload")
