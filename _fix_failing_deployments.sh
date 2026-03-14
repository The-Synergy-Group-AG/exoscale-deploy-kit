#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
KUBE=/home/iandre/.kube/config
KC="kubectl --kubeconfig=$KUBE --insecure-skip-tls-verify"

echo "=== 1. CORRECT METRICS after dashboard fix ==="
for QUERY in \
  'sum(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Running"})' \
  'sum(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Pending"})' \
  'sum(kube_pod_status_phase{namespace="exo-jtp-prod",phase="Failed"})' \
  'sum(kube_pod_status_phase{namespace="exo-jtp-prod",phase!="Running",phase!="Succeeded"})' \
  'count(kube_deployment_created{namespace="exo-jtp-prod"})' \
  'min(kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"})'; do
  RESULT=$(curl -s 'http://localhost:9090/api/v1/query' --data-urlencode "query=$QUERY" 2>/dev/null | python3 -c "
import json,sys; r=json.load(sys.stdin); res=r.get('data',{}).get('result',[]); print(res[0]['value'][1] if res else 'no data')
  " 2>/dev/null)
  echo "  $RESULT  ← $QUERY"
done

echo ""
echo "=== 2. Not-Available deployments with their images ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_deployment_status_condition{condition="Available",status="true",namespace="exo-jtp-prod"} == 0' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
for x in r.get('data',{}).get('result',[]):
    print(f'  {x[\"metric\"].get(\"deployment\",\"?\")}')
"

echo ""
echo "=== 3. Check pods for failing deployments via kubectl ==="
for DEP in docker-jtp godhood-consciousness-orchestrator user-profile-manager-service; do
  echo "--- $DEP ---"
  $KC get pods -n exo-jtp-prod -l "app=$DEP" --no-headers 2>/dev/null || \
  $KC get pods -n exo-jtp-prod --no-headers 2>/dev/null | grep "$DEP" | head -3
done

echo ""
echo "=== 4. Check docker-jtp deployment spec ==="
$KC get deployment docker-jtp -n exo-jtp-prod -o yaml 2>/dev/null | grep -E 'image:|replicas:|resources:|memory:|cpu:|reason:|message:' | head -20 || \
  echo "kubectl describe failed — trying events via prometheus"

echo ""
echo "=== 5. Pod events / reasons via prometheus ==="
# Check kube_pod_container_status_waiting_reason — shows WHY pods are pending
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_pod_container_status_waiting_reason{namespace="exo-jtp-prod"} > 0' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
from collections import Counter
reasons=Counter()
pods_by_reason={}
for x in results:
    reason=x['metric'].get('reason','?')
    pod=x['metric'].get('pod','?')
    reasons[reason]+=1
    pods_by_reason.setdefault(reason,[]).append(pod.split('-')[0] if len(pod)>30 else pod)
print(f'Containers in waiting state: {len(results)}')
for reason, count in reasons.most_common():
    print(f'  {reason}: {count} containers')
    for p in pods_by_reason[reason][:3]: print(f'    e.g.: {p}')
"

echo ""
echo "=== 6. Node resource pressure ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=kube_node_status_condition{condition="MemoryPressure",status="true"} == 1 OR kube_node_status_condition{condition="DiskPressure",status="true"} == 1' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
if results:
    for x in results:
        print(f'  NODE PRESSURE: {x[\"metric\"]}')
else:
    print('  No node pressure detected')
"

echo ""
echo "=== 7. kube_pod_container_resource_requests (resource quota issues?) ==="
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum by (resource)(kube_pod_container_resource_requests{namespace="exo-jtp-prod"})' \
  2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
for x in r.get('data',{}).get('result',[]):
    res=x['metric'].get('resource','?')
    val=float(x['value'][1])
    if res=='cpu': print(f'  Total CPU requests: {val:.2f} cores')
    elif res=='memory': print(f'  Total Memory requests: {val/1e9:.2f} GB')
"
