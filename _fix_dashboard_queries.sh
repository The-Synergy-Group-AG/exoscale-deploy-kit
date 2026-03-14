#!/bin/bash
# Fix dashboard panel issues:
# 1. Add labels to namespace so kube_namespace_labels works
# 2. Check node topology labels for Cluster Zone panel
# 3. Check why some deployments are not Available
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

KUBE=""
for K in /home/iandre/.kube/config /home/iandre/.kube/jtp-run4.yaml /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/kubeconfig*.yaml; do
  [ -f "$K" ] && KUBE="$K" && break
done
[ -z "$KUBE" ] && KUBE=$(ls /home/iandre/.kube/*.yaml 2>/dev/null | head -1)
echo "Using kubeconfig: $KUBE"

echo ""
echo "=== 1. Label namespace exo-jtp-prod (fixes kube_namespace_labels no data) ==="
if [ -n "$KUBE" ]; then
  kubectl --kubeconfig="$KUBE" label namespace exo-jtp-prod \
    project=jtp-bio-v3 plan=plan-125 run_id=20260305_125732 team=jtp --overwrite 2>&1 || \
    echo "[WARN] Could not label namespace"

  echo ""
  echo "=== 2. Node topology labels ==="
  kubectl --kubeconfig="$KUBE" get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range $k, $v := .metadata.labels}  {$k}={$v}{"\n"}{end}{end}' 2>/dev/null | grep -E 'zone|region|topology|failure|node.kubernetes' | head -20 || \
    kubectl --kubeconfig="$KUBE" get nodes --show-labels 2>&1 | head -5

  echo ""
  echo "=== 3. Not-Available deployments ==="
  kubectl --kubeconfig="$KUBE" get deployments -n exo-jtp-prod --field-selector=status.conditions[0].type=Available 2>/dev/null || \
  kubectl --kubeconfig="$KUBE" get deployments -n exo-jtp-prod -o json 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
not_available=[]
for d in data.get('items',[]):
  name=d['metadata']['name']
  conds=d.get('status',{}).get('conditions',[])
  avail=[c for c in conds if c['type']=='Available']
  if avail and avail[0]['status']!='True':
    not_available.append(name)
print(f'Not-Available deployments: {len(not_available)}')
for n in not_available[:10]: print(f'  {n}')
total=len(data.get('items',[]))
print(f'Total deployments checked: {total}')
"
else
  echo "[WARN] No kubeconfig found — listing candidates:"
  ls /home/iandre/.kube/ 2>/dev/null
  ls /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/*.yaml 2>/dev/null | head -5
fi

echo ""
echo "=== 4. KSM scrape — check node labels directly ==="
# Scrape KSM directly to see what kube_node_labels looks like
curl -s http://151.145.203.247:30808/metrics 2>/dev/null | grep '^kube_node_labels' | head -5 || \
  echo "  Cannot reach KSM directly"

echo ""
echo "=== 5. Wait for TSDB staleness to clear (3 min total since fix) ==="
echo "  Current kube_deployment_created count (expect ~220 when cleared):"
curl -s 'http://localhost:9090/api/v1/query' --data-urlencode 'query=count(kube_deployment_created{namespace="exo-jtp-prod"})' 2>/dev/null | python3 -c "
import json,sys
r=json.load(sys.stdin)
results=r.get('data',{}).get('result',[])
val = results[0]['value'][1] if results else 'no data'
print(f'  count: {val} (target: ~220)')
"
echo "  If still 660, wait ~5 more minutes for stale series to expire."
