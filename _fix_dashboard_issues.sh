#!/bin/bash
# Fix all dashboard issues systematically
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
KUBECONFIG=/home/iandre/.kube/config

echo "=== 1. CHECK actual node labels (for Cluster Zone query) ==="
kubectl --kubeconfig="$KUBECONFIG" get nodes --show-labels 2>/dev/null | grep -o 'topology[^ ]*' | head -20 || \
  kubectl --kubeconfig="$KUBECONFIG" get nodes -o json 2>/dev/null | python3 -c "
import json,sys
nodes=json.load(sys.stdin)['items']
for n in nodes[:1]:
    print('Node labels:')
    for k,v in sorted(n['metadata'].get('labels',{}).items()):
        print(f'  {k}={v}')
"

echo ""
echo "=== 2. CHECK kube_namespace_labels availability ==="
curl -s 'http://localhost:9090/api/v1/query?query=kube_namespace_labels' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'kube_namespace_labels: {len(results)} series')
for res in results[:3]:
    print(f'  labels: {res[\"metric\"]}')
"

echo ""
echo "=== 3. CHECK kube_node_labels availability ==="
curl -s 'http://localhost:9090/api/v1/query?query=kube_node_labels' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'kube_node_labels: {len(results)} series')
for res in results[:2]:
    print(f'  labels: {res[\"metric\"]}')
" 2>/dev/null || echo "  kube_node_labels not available yet (Prometheus just restarted)"

echo ""
echo "=== 4. FIX prometheus.yml KSM targets (Windows mount path) ==="
PROM_WIN="/mnt/c/Users/andre/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml"
python3 -X utf8 << PYEOF
from pathlib import Path
p = Path("/mnt/c/Users/andre/StarGate/10 Projects/Agent Zero/repos/agent-zero-agents/prometheus.yml")
content = p.read_text(encoding='utf-8')
old = """      - targets:
          - '151.145.203.247:30808'
          - '91.92.142.14:30808'
          - '151.145.200.72:30808'"""
new = """      - targets:
          - '151.145.203.247:30808'
          # LESSON 37: Only ONE target needed — kube-state-metrics is a single pod.
          # NodePort routes all 3 IPs to same pod. 3 targets = 3x data triplication!
          # Inactive IPs: 91.92.142.14:30808, 151.145.200.72:30808"""
if old in content:
    content = content.replace(old, new)
    p.write_text(content, encoding='utf-8')
    print("[OK] prometheus.yml: KSM reduced to 1 target")
else:
    import re
    m = re.findall(r"'[\d.]+:30808'", content)
    print(f"[INFO] Current 30808 targets in file: {m}")
PYEOF

echo ""
echo "=== 5. CHECK jtp_deployment_info metric (DEPLOY FAILED source) ==="
curl -s 'http://localhost:9090/api/v1/query?query=jtp_deployment_info' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'jtp_deployment_info: {len(results)} series')
for res in results[:2]:
    print(f'  {res[\"metric\"]}')
" || echo "  jtp_deployment_info: no data"

echo ""
echo "=== 6. CHECK deployment Available conditions ==="
curl -s 'http://localhost:9090/api/v1/query?query=count(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(f'Deployments Available=true: {val}')
"

echo ""
echo "=== 7. RESTART Prometheus with fixed config ==="
docker restart agent-zero-agents-prometheus-1 >/dev/null 2>&1
echo "[OK] Prometheus restarted"
sleep 8
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json,sys
r=json.load(sys.stdin)
kube=[t for t in r.get('data',{}).get('activeTargets',[]) if 'kube' in t['labels'].get('job','')]
print(f'KSM targets: {len(kube)}')
for t in kube: print(f'  {t[\"scrapeUrl\"]} {t[\"health\"]}')
"
