#!/bin/bash
export KUBECONFIG=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260304_085857/kubeconfig.yaml

echo "=== Applying ClusterIssuer + Ingress ==="
kubectl apply -f /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/ingress-tls.yaml

echo ""
echo "=== Waiting up to 90s for nginx-ingress LoadBalancer IP ==="
for i in $(seq 1 18); do
    IP=$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
        -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
    if [ -n "$IP" ]; then
        echo ""
        echo "======================================"
        echo "NGINX INGRESS LB IP: $IP"
        echo "======================================"
        echo ""
        echo "ACTION REQUIRED — update DNS A records:"
        echo "  jobtrackerpro.ch     A   $IP"
        echo "  www.jobtrackerpro.ch A   $IP"
        echo ""
        echo "Then cert-manager will auto-issue a Let's Encrypt cert."
        echo "Monitor cert status with:"
        echo "  kubectl -n exo-jtp-prod get certificate jobtrackerpro-tls"
        break
    fi
    echo "attempt $i/18: LB IP still pending... (${i}x5s)"
    sleep 5
done

echo ""
echo "=== Ingress status ==="
kubectl -n exo-jtp-prod get ingress 2>&1

echo ""
echo "=== nginx-ingress LB service ==="
kubectl -n ingress-nginx get svc ingress-nginx-controller 2>&1
