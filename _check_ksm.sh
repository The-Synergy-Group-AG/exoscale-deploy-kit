#!/bin/bash
KC=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/kubeconfig.yaml

echo "=== kube-state-metrics pods ==="
kubectl get pods -n kube-system --kubeconfig="$KC" --no-headers 2>&1 | grep -i 'kube-state\|metrics'

echo ""
echo "=== kube-state-metrics service ==="
kubectl get svc -n kube-system --kubeconfig="$KC" 2>&1 | grep -i 'kube-state\|30808'

echo ""
echo "=== NodePort 30808 test ==="
curl -s --max-time 5 http://151.145.203.247:30808/metrics 2>&1 | head -3

echo ""
echo "=== engines/deployment_engine/outputs/manifests ==="
ls /home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs/manifests/ | head -5
echo "Count: $(ls /home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs/manifests/ 2>/dev/null | wc -l)"

echo ""
echo "=== exoscale-deploy-kit/outputs/20260305_125732 ==="
ls /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/
