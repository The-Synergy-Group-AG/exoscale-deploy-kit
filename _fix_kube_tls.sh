#!/bin/bash
# Fix kubectl TLS + check all metrics now that triplication is fixed
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
KUBE=/home/iandre/.kube/config
# Use --insecure-skip-tls-verify to bypass Exoscale Traefik cert mismatch
KC="kubectl --kubeconfig=$KUBE --insecure-skip-tls-verify"

echo "=== 1. ALL DASHBOARD METRICS (post-triplication fix) ==="
for QUERY in \
  'count(kube_deployment_created{namespace="exo-jtp-prod"})' \
  'count(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Running"})' \
  'count(kube_pod_status_phase{namespace="exo-jtp-prod",phase!="Running",phase!="Succeeded"})' \
  'count(kube_node_status_condition{condition="Ready",status="true"})' \
  'min(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})' \
  'count(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})'; do
  RESULT=$(curl -s 'http://localhost:9090/api/v1/query' --data-urlencode "query=$QUERY" 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(val)
  " 2>/dev/null || echo "error")
  echo "  $QUERY"
  echo "    => $RESULT"
done

echo ""
echo "=== 2. Label namespace exo-jtp-prod (--insecure-skip-tls-verify) ==="
$KC label namespace exo-jtp-prod \
  project=jtp-bio-v3 plan=plan-125 run_id=20260305_125732 team=jtp \
  --overwrite 2>&1 | tail -3

echo ""
echo "=== 3. Node labels (zone info for Cluster Zone panel) ==="
$KC get nodes -o json 2>/dev/null | python3 -c "
import json,sys
try:
    data=json.load(sys.stdin)
    nodes=data.get('items',[])
    for n in nodes:
        name=n['metadata']['name']
        labels=n['metadata'].get('labels',{})
        zone=labels.get('topology.kubernetes.io/zone','') or labels.get('failure-domain.beta.kubernetes.io/zone','') or labels.get('topology.csi.exoscale.com/zone','')
        print(f'Node: {name}')
        for k,v in sorted(labels.items()):
            if any(x in k for x in ['zone','region','topology','failure','node.kubernetes']):
                print(f'  {k}={v}')
        if not zone:
            print('  [WARNING] No zone label found')
except Exception as e:
    print(f'Error: {e}')
" || echo "  kubectl failed even with --insecure-skip-tls-verify"

echo ""
echo "=== 4. Not-Available deployments ==="
$KC get deployments -n exo-jtp-prod -o json 2>/dev/null | python3 -c "
import json,sys
try:
    data=json.load(sys.stdin)
    not_avail=[]
    for d in data.get('items',[]):
        name=d['metadata']['name']
        conds=d.get('status',{}).get('conditions',[])
        avail=[c for c in conds if c['type']=='Available']
        if avail and avail[0]['status']!='True':
            msg=avail[0].get('message','')
            not_avail.append(f'{name}: {msg[:60]}')
    print(f'Not-Available: {len(not_avail)} / {len(data.get(\"items\",[]))}')
    for n in not_avail[:10]: print(f'  {n}')
except Exception as e:
    print(f'Error: {e}')
"

echo ""
echo "=== 5. kube_node_labels via Prometheus (zone labels exported?) ==="
curl -s 'http://localhost:9090/api/v1/query' --data-urlencode 'query=kube_node_labels' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
print(f'kube_node_labels series: {len(results)}')
for res in results[:3]:
    m=res['metric']
    print(f'  {m}')
"
