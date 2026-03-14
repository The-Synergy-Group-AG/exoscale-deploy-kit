#!/bin/bash
set -e
KC="--kubeconfig /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260306_104844/kubeconfig.yaml --insecure-skip-tls-verify"
NS="-n exo-jtp-prod"
FRONTEND=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/frontend

echo "=== Step 1: Apply nginx configmaps + deployment + service ==="
kubectl apply $KC $NS -f $FRONTEND/frontend-k8s.yaml

echo ""
echo "=== Step 2: Inject real index.html into ConfigMap ==="
kubectl create configmap frontend-html \
  $KC $NS \
  --from-file=index.html=$FRONTEND/index.html \
  --dry-run=client -o yaml | kubectl apply $KC $NS -f -

echo ""
echo "=== Step 3: Restart deployment to pick up new ConfigMap ==="
kubectl rollout restart $KC $NS deployment/frontend-nginx
kubectl rollout status $KC $NS deployment/frontend-nginx --timeout=60s

echo ""
echo "=== Step 4: Patch ingress to route / → nginx, /api/ → gateway ==="
kubectl patch ingress docker-jtp-ingress $KC $NS --type=json -p='[
  {
    "op": "replace",
    "path": "/spec/rules/0/http/paths",
    "value": [
      {
        "path": "/api/",
        "pathType": "Prefix",
        "backend": {"service": {"name": "docker-jtp", "port": {"number": 80}}}
      },
      {
        "path": "/health",
        "pathType": "Exact",
        "backend": {"service": {"name": "docker-jtp", "port": {"number": 80}}}
      },
      {
        "path": "/",
        "pathType": "Prefix",
        "backend": {"service": {"name": "frontend-nginx", "port": {"number": 80}}}
      }
    ]
  },
  {
    "op": "replace",
    "path": "/spec/rules/1/http/paths",
    "value": [
      {
        "path": "/api/",
        "pathType": "Prefix",
        "backend": {"service": {"name": "docker-jtp", "port": {"number": 80}}}
      },
      {
        "path": "/",
        "pathType": "Prefix",
        "backend": {"service": {"name": "frontend-nginx", "port": {"number": 80}}}
      }
    ]
  }
]'

echo ""
echo "=== Step 5: Verify ==="
kubectl get pods $KC $NS -l app=frontend-nginx
kubectl get ingress $KC $NS docker-jtp-ingress

echo ""
echo "=== Step 6: HTTP check (wait 5s for nginx-ingress to re-sync) ==="
sleep 5
python3 -c "
import urllib.request
req = urllib.request.urlopen('https://jobtrackerpro.ch/', timeout=10)
body = req.read().decode()
print(f'Status: {req.status}  Size: {len(body)} bytes')
if '<!DOCTYPE' in body or '<html' in body.lower():
    print('[OK] HTML dashboard is live at https://jobtrackerpro.ch/')
    # Print title line
    for line in body.splitlines():
        if '<title>' in line:
            print(f'Title: {line.strip()}')
            break
else:
    print(f'[INFO] Response: {body[:200]}')
"
