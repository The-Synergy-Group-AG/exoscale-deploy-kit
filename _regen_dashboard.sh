#!/bin/bash
set -e
KC="--kubeconfig /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260306_104844/kubeconfig.yaml --insecure-skip-tls-verify"
NS="-n exo-jtp-prod"
FRONTEND=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/frontend

echo "=== Getting actual K8s service names (219 app services) ==="
kubectl get svc $KC $NS --no-headers 2>/dev/null \
  | grep -v '^docker-jtp \|^frontend-nginx \|^ingress\|nginx-ingress\|^kubernetes \|cert-manager\|^acme-' \
  | awk '{print $1}' \
  | sort \
  > /tmp/actual_services.txt

COUNT=$(wc -l < /tmp/actual_services.txt)
echo "Found $COUNT services"

echo "=== Generating SERVICES JS array ==="
python3 << 'PYEOF'
with open('/tmp/actual_services.txt') as f:
    services = [s.strip() for s in f if s.strip()]
print(f"Total: {len(services)}")
lines = []
chunk = []
for i, s in enumerate(services):
    chunk.append(f'"{s}"')
    if len(chunk) == 4 or i == len(services) - 1:
        lines.append("  " + ",".join(chunk))
        chunk = []
js = "const SERVICES = [\n" + ",\n".join(lines) + "\n];"
with open('/tmp/services_js.txt', 'w') as f:
    f.write(js)
print(f"JS array written ({len(js)} chars)")
PYEOF

echo "=== Patching index.html ==="
cd $FRONTEND
python3 << 'PYEOF'
with open('index.html', 'r') as f:
    html = f.read()
with open('/tmp/services_js.txt', 'r') as f:
    new_services = f.read()
import re
pattern = r'const SERVICES = \[[\s\S]*?\];'
new_html = re.sub(pattern, new_services, html)
if new_html == html:
    print("ERROR: SERVICES pattern not found!")
    exit(1)
with open('index.html', 'w') as f:
    f.write(new_html)
print(f"index.html updated ({len(new_html)} bytes)")
PYEOF

echo "=== Updating ConfigMap ==="
kubectl create configmap frontend-html \
  $KC $NS \
  --from-file=index.html=$FRONTEND/index.html \
  --dry-run=client -o yaml | kubectl apply $KC $NS -f -

echo "=== Restarting nginx ==="
kubectl rollout restart $KC $NS deployment/frontend-nginx
kubectl rollout status $KC $NS deployment/frontend-nginx --timeout=60s

echo "=== Verify ==="
sleep 3
python3 -c "
import urllib.request, re
req = urllib.request.urlopen('https://jobtrackerpro.ch/', timeout=10)
body = req.read().decode()
print(f'HTTPS {req.status} | {len(body)} bytes')
m = re.search(r'const SERVICES = \[(.*?)\];', body, re.DOTALL)
if m:
    count = m.group(1).count('\"') // 2
    print(f'Services in dashboard: {count}')
"
echo "Done!"
