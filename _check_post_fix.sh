#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== Waiting 35s for Prometheus scrape cycle ==="
sleep 35

echo ""
echo "=== 1. KEY COUNTS after triplication fix ==="
for QUERY in \
  "count(kube_deployment_created{namespace='exo-jtp-prod'})" \
  "count(kube_pod_status_phase{namespace='exo-jtp-prod',phase='Running'})" \
  "count(kube_node_status_condition{condition='Ready',status='true'})" \
  "count(kube_namespace_labels{namespace='exo-jtp-prod'})"; do
  ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$QUERY")
  RESULT=$(curl -s "http://localhost:9090/api/v1/query?query=$ENCODED" | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(val)
  " 2>/dev/null || echo "error")
  echo "  $QUERY = $RESULT"
done

echo ""
echo "=== 2. Exoscale node labels (for Cluster Zone panel fix) ==="
# Find kubeconfig
KUBE=""
for K in /home/iandre/.kube/config /root/.kube/config; do
  [ -f "$K" ] && KUBE="$K" && break
done
if [ -n "$KUBE" ]; then
  kubectl --kubeconfig="$KUBE" get nodes -o json 2>/dev/null | python3 -c "
import json,sys
nodes=json.load(sys.stdin)['items']
for n in nodes[:1]:
    print('Node:', n['metadata']['name'])
    for k,v in sorted(n['metadata'].get('labels',{}).items()):
        if any(x in k for x in ['zone','region','topology','failure']):
            print(f'  ZONE LABEL: {k}={v}')
" || echo "  kubectl failed"
else
  echo "  No kubeconfig found"
fi

echo ""
echo "=== 3. kube_node_labels — what labels KSM exports ==="
curl -s 'http://localhost:9090/api/v1/query?query=kube_node_labels' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'Total kube_node_labels series: {len(results)}')
for res in results[:2]:
    m=res['metric']
    zone_labels={k:v for k,v in m.items() if 'zone' in k or 'topo' in k}
    print(f'  node={m.get(\"node\",\"?\")} zone_labels={zone_labels}')
    print(f'  ALL: {list(m.keys())[:10]}')
"

echo ""
echo "=== 4. What kube_node_labels label_ keys are available? ==="
curl -s 'http://localhost:9090/api/v1/labels' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
labels=[l for l in r.get('data',[]) if 'label_topology' in l or 'label_zone' in l or 'label_failure' in l]
print('Zone-related label keys in Prometheus:', labels[:10])
"

echo ""
echo "=== 5. Deployment Available check ==="
curl -s 'http://localhost:9090/api/v1/query' --data-urlencode 'query=count(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(f'Deployments Available=true: {val}')
"

echo ""
echo "=== 6. Min deployment Available (drives DEPLOY FAILED/SUCCESS) ==="
curl -s 'http://localhost:9090/api/v1/query' --data-urlencode 'query=min(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(f'min(Available=true): {val} — Dashboard shows DEPLOY SUCCESS if =1, FAILED if =0')
"
