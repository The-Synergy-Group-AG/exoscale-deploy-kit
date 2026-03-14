#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== 1. Pod phase breakdown in exo-jtp-prod ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=count by (phase) (kube_pod_status_phase{namespace="exo-jtp-prod"})' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print('Pod phases:')
for res in sorted(results, key=lambda x: -float(x['value'][1])):
    phase=res['metric'].get('phase','?')
    val=res['value'][1]
    print(f'  {phase}: {val}')
"

echo ""
echo "=== 2. Deployments where Available=true value=0 (not ready) ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"} == 0' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'Not-Available deployments: {len(results)}')
for res in results[:15]:
    print(f'  {res[\"metric\"].get(\"deployment\",\"?\")}')
total_true = None
" 

echo ""
echo "=== 3. Deployment replica status ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_deployment_status_replicas_unavailable{namespace="exo-jtp-prod"} > 0' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'Deployments with unavailable replicas: {len(results)}')
for res in results[:10]:
    d=res['metric'].get('deployment','?')
    v=res['value'][1]
    print(f'  {d}: {v} unavailable')
"

echo ""
echo "=== 4. Pods pending breakdown ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=count by (namespace)(kube_pod_status_phase{phase="Pending"})' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print('Pending pods by namespace:')
for res in sorted(results, key=lambda x: -float(x['value'][1])):
    ns=res['metric'].get('namespace','?')
    v=res['value'][1]
    print(f'  {ns}: {v}')
"

echo ""
echo "=== 5. Fix kubectl — try using exo CLI to get fresh kubeconfig ==="
# Try exo CLI to get fresh kubeconfig for Run 4
EXO=$(which exo 2>/dev/null || echo "")
if [ -n "$EXO" ]; then
  echo "exo found at $EXO"
  exo compute sks list 2>/dev/null | head -5
else
  echo "exo CLI not found"
fi
# Try with KUBECONFIG that has insecure embedded
kubectl --kubeconfig=/home/iandre/.kube/config --insecure-skip-tls-verify get pods -n exo-jtp-prod --field-selector=status.phase=Pending --no-headers 2>/dev/null | head -5 || \
  echo "kubectl Pending pods query failed"

echo ""
echo "=== 6. kube_node_labels raw from KSM metrics ==="
curl -s http://151.145.203.247:30808/metrics 2>/dev/null | grep -E '^kube_node_labels|^kube_node_info' | head -5 || echo "Cannot reach KSM directly (firewall)"
# Try via internal IP if NodePort not reachable
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_node_info' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'kube_node_info series: {len(results)}')
for res in results[:3]:
    m=res['metric']
    zone_keys={k:v for k,v in m.items() if 'zone' in k.lower() or 'region' in k.lower()}
    print(f'  node={m.get(\"node\",\"?\")} zone={zone_keys}')
    print(f'  all keys: {sorted(m.keys())}')
"
