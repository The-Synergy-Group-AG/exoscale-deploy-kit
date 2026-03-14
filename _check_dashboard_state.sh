#!/bin/bash
# Check dashboard data state
KUBECONFIG=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/kubeconfig.yaml

echo "=== CURRENT NODE IPs ==="
kubectl get nodes -o wide --kubeconfig="$KUBECONFIG" --no-headers 2>&1 | awk '{print $1, $6}'

echo ""
echo "=== PORT 8005 KEY METRICS ==="
curl -s http://localhost:8005/metrics 2>/dev/null | grep -E '^jtp_deploy|^jtp_kube|^jtp_pod|^jtp_service|^jtp_node' | head -30

echo ""
echo "=== PORT 8005 ALL METRIC NAMES ==="
curl -s http://localhost:8005/metrics 2>/dev/null | grep '^# HELP' | awk '{print $3}' | head -30

echo ""
echo "=== PROMETHEUS.YML kube-state lines ==="
grep -A3 'kube-state\|kube_state\|30808' /home/iandre/projects/jtp-bio-v3/monitoring/prometheus/prometheus.yml
