#!/bin/bash
# Deploy kube-state-metrics to Run 4 cluster with NodePort 30808
# Lesson 27: helm is in ~/.local/bin
export PATH="$HOME/.local/bin:$PATH"
set -euo pipefail

KC=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/kubeconfig.yaml

echo "=== Deploying kube-state-metrics to Run 4 cluster ==="
echo "Helm: $(helm version --short 2>/dev/null || echo NOT FOUND)"

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update prometheus-community 2>/dev/null

helm upgrade --install kube-state-metrics prometheus-community/kube-state-metrics \
  --namespace kube-system \
  --kubeconfig="$KC" \
  --set service.type=NodePort \
  --set service.nodePort=30808 \
  --set resources.requests.cpu=10m \
  --set resources.requests.memory=32Mi \
  --set resources.limits.cpu=100m \
  --set resources.limits.memory=128Mi \
  --wait --timeout=120s 2>&1

echo ""
echo "=== Verifying NodePort 30808 ==="
kubectl get svc kube-state-metrics -n kube-system --kubeconfig="$KC" 2>&1

echo ""
echo "=== Testing port 30808 (wait 10s) ==="
sleep 10
curl -s --max-time 5 http://151.145.203.247:30808/metrics 2>&1 | head -5
