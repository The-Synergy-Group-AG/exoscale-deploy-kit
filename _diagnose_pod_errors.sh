#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
KUBE=/home/iandre/.kube/config
KC="kubectl --kubeconfig=$KUBE --insecure-skip-tls-verify"

echo "=== 1. ALL waiting reasons (not just > 0) ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_pod_container_status_waiting_reason{namespace="exo-jtp-prod"}' \
  2>/dev/null | python3 -c "
import json,sys
from collections import Counter
r=json.load(sys.stdin)
reasons=Counter()
for x in r.get('data',{}).get('result',[]):
    val=float(x['value'][1])
    if val > 0:
        reasons[x['metric'].get('reason','?')] += 1
print('Active waiting reasons:')
for reason, count in reasons.most_common():
    print(f'  {reason}: {count}')
total = len([x for x in r.get('data',{}).get('result',[]) if float(x['value'][1])>0])
print(f'Total waiting containers: {total}')
"

echo ""
echo "=== 2. dockerhub-creds secret check ==="
$KC get secret dockerhub-creds -n exo-jtp-prod 2>&1 | head -3

echo ""
echo "=== 3. All pods not Running ==="
$KC get pods -n exo-jtp-prod 2>/dev/null | grep -v 'Running\|Completed' | head -20

echo ""
echo "=== 4. Pod describe for docker-jtp ==="
GATEWAY_POD=$($KC get pods -n exo-jtp-prod 2>/dev/null | grep 'docker-jtp' | head -1 | awk '{print $1}')
if [ -n "$GATEWAY_POD" ]; then
    $KC describe pod "$GATEWAY_POD" -n exo-jtp-prod 2>/dev/null | grep -E 'Status:|Reason:|Message:|State:|Exit Code:|Image:|Error:|Warning:' | head -20
else
    echo "  Could not find docker-jtp pod name"
    # Try listing ALL pods
    $KC get pods -n exo-jtp-prod --no-headers 2>/dev/null | head -5
fi

echo ""
echo "=== 5. Resource quota in namespace ==="
$KC get resourcequota -n exo-jtp-prod 2>/dev/null || echo "  No resource quota or kubectl failed"

echo ""
echo "=== 6. Check HPA that may have scaled services to 2 replicas ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_horizontalpodautoscaler_spec_min_replicas{namespace="exo-jtp-prod"}' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'HPAs: {len(results)}')
for x in results[:5]:
    print(f'  hpa={x[\"metric\"].get(\"horizontalpodautoscaler\",\"?\")} min={x[\"value\"][1]}')
"

echo ""
echo "=== 7. memory limit < request check in manifests ==="
python3 -c "
import yaml, os
from pathlib import Path

outputs_dir = Path('/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/k8s-services-20260305_125730')
bad_resources = []
for f in outputs_dir.glob('*.yaml'):
    try:
        docs = list(yaml.safe_load_all(f.read_text()))
        for doc in docs:
            if not doc or doc.get('kind') != 'Deployment': continue
            containers = doc.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[])
            for c in containers:
                res = c.get('resources',{})
                req_mem = res.get('requests',{}).get('memory','')
                lim_mem = res.get('limits',{}).get('memory','')
                def to_mi(s):
                    if not s: return 0
                    s=str(s)
                    if s.endswith('Mi'): return int(s[:-2])
                    if s.endswith('Gi'): return int(s[:-2])*1024
                    return 0
                if to_mi(lim_mem) < to_mi(req_mem) and to_mi(req_mem) > 0:
                    bad_resources.append(f'{f.name}: req={req_mem} limit={lim_mem}')
    except: pass

print(f'Manifests with memory limit < request: {len(bad_resources)}')
for b in bad_resources[:20]: print(f'  {b}')
"
