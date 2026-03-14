#!/bin/bash
# Diagnose dashboard queries and fix KSM triplication
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== 1. FIX: prometheus.yml — reduce KSM to 1 target (fixes triplication) ==="
PROM_YML="$HOME/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml"
python3 -X utf8 << 'PYEOF'
import re
from pathlib import Path
p = Path("/root/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml")
if not p.exists():
    # Try with home dir
    import os
    p = Path(os.path.expanduser("~/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml"))

content = p.read_text()

# Replace the 3-target block with a single target (first IP only)
# Pattern: targets block under jtp-kube-state-metrics with 3 IPs
old_block = """      - targets:
          - '151.145.203.247:30808'
          - '91.92.142.14:30808'
          - '151.145.200.72:30808'"""
new_block = """      - targets:
          - '151.145.203.247:30808'
          # Note: Only ONE target needed — kube-state-metrics is a single pod.
          # NodePort routes all 3 IPs to the same pod. Using 3 targets = 3x data!
          # Run 4 Node IPs (inactive): 91.92.142.14:30808, 151.145.200.72:30808"""

if old_block in content:
    content = content.replace(old_block, new_block)
    p.write_text(content)
    print("[OK] prometheus.yml: KSM reduced to 1 target (was 3x triplication)")
else:
    print("[WARN] Old 3-target block not found in prometheus.yml — check manually")
    # Show current KSM targets
    for line in content.split('\n'):
        if '30808' in line:
            print(f"  Found: {line}")
PYEOF

echo ""
echo "=== 2. DIAGNOSE: Dashboard queries for broken panels ==="
python3 -X utf8 << 'PYEOF2'
import json
from pathlib import Path

dashboard_path = Path("/home/iandre/projects/jtp-bio-v3/monitoring/grafana/dashboards/jtp-deployment-dashboard.json")
if not dashboard_path.exists():
    print(f"[ERROR] Dashboard not found at {dashboard_path}")
    exit(1)

data = json.loads(dashboard_path.read_text())
panels = data.get('panels', [])

print(f"Dashboard: {data.get('title', 'Unknown')}")
print(f"Total panels: {len(panels)}")
print()

# Extract all panel titles + their expressions
for panel in panels:
    title = panel.get('title', 'Untitled')
    panel_type = panel.get('type', '')
    
    # Get all targets/expressions
    targets = panel.get('targets', [])
    exprs = [t.get('expr', '') for t in targets if t.get('expr')]
    
    # Also check nested panels (rows)
    sub_panels = panel.get('panels', [])
    for sp in sub_panels:
        sp_title = sp.get('title', 'Untitled')
        sp_targets = sp.get('targets', [])
        sp_exprs = [t.get('expr', '') for t in sp_targets if t.get('expr')]
        if sp_exprs:
            print(f"  [{sp_title}]")
            for e in sp_exprs:
                print(f"    EXPR: {e[:120]}")
    
    if exprs and any(kw in title.lower() for kw in ['state', 'deploy', 'image', 'zone', 'namespace', 'fads', 'services deploy', 'pods', 'node', 'health', 'docker']):
        print(f"[{title}] ({panel_type})")
        for e in exprs:
            print(f"  EXPR: {e[:120]}")
        print()
PYEOF2

echo ""
echo "=== 3. Restart Prometheus after config change ==="
PROM_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -i prometheus | head -1 || true)
if [ -n "$PROM_CONTAINER" ]; then
    docker restart "$PROM_CONTAINER" >/dev/null 2>&1
    echo "[OK] Prometheus restarted: $PROM_CONTAINER"
    sleep 5
    echo "KSM targets after restart:"
    curl -s http://localhost:9090/api/v1/targets 2>/dev/null | python3 -c "import json,sys; r=json.load(sys.stdin); kube=[t for t in r.get('data',{}).get('activeTargets',[]) if 'kube' in t['labels'].get('job','')]; [print(t['scrapeUrl'], t['health']) for t in kube]; print('TOTAL:', len(kube))"
else
    echo "[WARN] Prometheus container not found"
fi
