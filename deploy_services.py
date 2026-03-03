#!/usr/bin/env python3
"""
deploy_services.py — Deploy all 219 JTP services to the live Exoscale SKS cluster
===================================================================================
Architecture: 1-pod-per-service (Plan 122 / Plan 121 lessons learned)

Each service uses the SAME docker-jtp image, activated via SERVICE_NAME env var:
  - start.sh detects SERVICE_NAME → runs /app/services/<name>/main.py on port 8000
  - If no main.py (frontend stubs), start.sh auto-generates a FastAPI stub
  - SERVICE_NAME absent → gateway mode (app.py, port 5000)

Gateway routes: /api/{service_name}/{path} → http://{service-dns-name}:8000/{path}
  The gateway does: service_name.replace("_", "-") for DNS resolution
  So: auth_service → auth-service (K8s ClusterIP service DNS)

Resource sizing per service (lightweight FastAPI stub):
  requests: cpu=50m, memory=64Mi
  limits:   cpu=200m, memory=128Mi
  219 services × 64Mi = ~14GB memory requests (fits in 24GB cluster) ✅
  219 services × 50m  = ~11 CPUs (fits in 24 CPUs) ✅

Usage:
  cd exoscale-deploy-kit
  python3 -X utf8 deploy_services.py --kubeconfig outputs/20260303_165856/kubeconfig.yaml
  python3 -X utf8 deploy_services.py --kubeconfig outputs/20260303_165856/kubeconfig.yaml --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── CLI ───────────────────────────────────────────────────────────────────────
_p = argparse.ArgumentParser()
_p.add_argument("--kubeconfig", default=None, help="Path to kubeconfig.yaml (default: KUBECONFIG env)")
_p.add_argument("--namespace",  default="exo-jtp-prod")
_p.add_argument("--image",      default="iandrewitz/docker-jtp:7")
_p.add_argument("--dry-run",    action="store_true", help="Generate manifests but do not apply")
_p.add_argument("--service",    default=None, help="Deploy only this one service (for testing)")
_args = _p.parse_args()

KUBE = _args.kubeconfig or os.environ.get("KUBECONFIG", "")
NS   = _args.namespace
IMG  = _args.image

KIT_DIR       = Path(__file__).parent
MANIFEST_FILE = KIT_DIR / "service" / "services_manifest.json"
OUT_DIR       = KIT_DIR / "outputs" / f"services_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}]  {msg}")
def ok(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}] OK {msg}")
def warn(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def fail(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL {msg}")


# Frontend services: names containing "frontend" or equal to "frontend-api-gateway"
# These have no main.py in the image — start.sh tries to write one but fails with
# PermissionError because the image directory is owned by root and we run as user 1000.
# Fix: bypass start.sh entirely with inline Python (no filesystem write needed).
FRONTEND_SERVICES = {
    "ai-conversation-frontend",
    "credits-redemption-frontend",
    "frontend-api-gateway",
    "gamification-frontend",
    "interview-prep-frontend",
    "networking-frontend",
    "notifications-center-frontend",
    "onboarding-frontend",
    "payment-billing-frontend",
    "rav-compliance-frontend",
    "shared-components-library-frontend",
}


def svc_dns_name(name: str) -> str:
    """Convert service name to K8s DNS-safe name (underscores → hyphens)."""
    return name.replace("_", "-")


def is_frontend(service_name: str) -> bool:
    """Frontend services have no main.py — must use inline Python command."""
    dns = svc_dns_name(service_name)
    return dns in FRONTEND_SERVICES or "frontend" in dns


def generate_service_manifest(service_name: str) -> str:
    """
    Generate K8s Deployment + ClusterIP Service YAML for a single service.

    Key design decisions:
    - ClusterIP (NOT LoadBalancer) — only the gateway is externally exposed
    - Backend services: SERVICE_NAME env activates start.sh SERVICE mode (port 8000)
    - Frontend services: inline Python command bypasses start.sh (PermissionError fix)
      Root cause: frontend dirs owned by root in image; user 1000 can't write main.py
    - Port 8000 (not 5000 — 5000 is the gateway port)
    - 1 replica — services are stateless stubs, 1 is enough
    - Resources: 50m CPU / 64Mi memory (lightweight FastAPI stub)
    """
    dns_name  = svc_dns_name(service_name)
    frontend  = is_frontend(service_name)
    svc_label = "frontend-stub" if frontend else "backend"

    # Frontend: inline Python bypasses start.sh entirely — no file writes needed
    command_block = ""
    if frontend:
        command_block = f"""        command:
        - "python3"
        - "-c"
        - |
          import uvicorn
          from fastapi import FastAPI
          app = FastAPI(title="{service_name}")
          @app.get("/")
          def root():
              return {{"service": "{service_name}", "type": "frontend-stub", "status": "running"}}
          @app.get("/health")
          def health():
              return {{"status": "healthy", "service": "{service_name}"}}
          uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
"""

    return f"""---
# Service: {service_name}  [{svc_label}]
# DNS: {dns_name}.{NS}.svc.cluster.local:8000
# Gateway routes: /api/{service_name}/* → http://{dns_name}:8000/*
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {dns_name}
  namespace: {NS}
  labels:
    app: {dns_name}
    service-name: "{service_name}"
    service-type: "{svc_label}"
    managed-by: deploy-services-py
    version: "7"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {dns_name}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app: {dns_name}
        service-name: "{service_name}"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      imagePullSecrets:
      - name: dockerhub-creds
      containers:
      - name: {dns_name}
        image: {IMG}
        imagePullPolicy: IfNotPresent
{command_block}        ports:
        - containerPort: 8000
          protocol: TCP
        env:
        - name: SERVICE_NAME
          value: "{service_name}"
        - name: ENVIRONMENT
          value: "production"
        resources:
          requests:
            cpu: "25m"      # Reduced from 50m — 219×25m=5.5 CPUs fits in 3×4vCPU cluster
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 30
          failureThreshold: 3
---
apiVersion: v1
kind: Service
metadata:
  name: {dns_name}
  namespace: {NS}
  labels:
    app: {dns_name}
    service-name: "{service_name}"
    managed-by: deploy-services-py
spec:
  type: ClusterIP
  selector:
    app: {dns_name}
  ports:
  - name: http
    port: 8000
    targetPort: 8000
    protocol: TCP
"""


def kubectl(args: list, input_data: str | None = None) -> tuple[int, str, str]:
    """Run kubectl with the configured kubeconfig."""
    cmd = ["kubectl"]
    if KUBE:
        cmd += ["--kubeconfig", KUBE]
    cmd += args
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_data)
    return r.returncode, r.stdout, r.stderr


def main():
    # Load services manifest
    if not MANIFEST_FILE.exists():
        fail(f"services_manifest.json not found: {MANIFEST_FILE}")
        sys.exit(1)

    manifest_data = json.loads(MANIFEST_FILE.read_text())
    all_services  = manifest_data.get("services", [])

    if _args.service:
        all_services = [s for s in all_services if s == _args.service]
        if not all_services:
            fail(f"Service '{_args.service}' not found in services_manifest.json")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  DEPLOY SERVICES — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Image:     {IMG}")
    print(f"  Namespace: {NS}")
    print(f"  Services:  {len(all_services)}")
    print(f"  Mode:      {'DRY RUN' if _args.dry_run else 'LIVE'}")
    print(f"  Manifests: {OUT_DIR}")
    print(f"{'='*60}\n")

    if not _args.dry_run and not KUBE:
        fail("--kubeconfig or KUBECONFIG env var required for live deployment")
        sys.exit(1)

    # Generate all manifests
    log(f"Generating {len(all_services)} service manifests...")
    manifest_paths = []
    for svc_name in all_services:
        yaml_content = generate_service_manifest(svc_name)
        yaml_path = OUT_DIR / f"{svc_dns_name(svc_name)}.yaml"
        yaml_path.write_text(yaml_content)
        manifest_paths.append(yaml_path)

    ok(f"Generated {len(manifest_paths)} manifests in {OUT_DIR}")

    if _args.dry_run:
        log("DRY RUN: manifests written, no kubectl apply executed")
        log(f"To apply: kubectl --kubeconfig <kube> apply -f {OUT_DIR}/")
        sys.exit(0)

    # Apply all manifests in one kubectl call (much faster than one-by-one)
    log(f"\nApplying all {len(all_services)} service manifests...")
    t0 = time.time()

    rc, stdout, stderr = kubectl(
        ["apply", "-f", str(OUT_DIR) + "/", "--validate=false"]
    )

    if rc == 0:
        lines = [l for l in stdout.strip().split("\n") if l]
        created   = [l for l in lines if "created"   in l]
        configured = [l for l in lines if "configured" in l]
        unchanged = [l for l in lines if "unchanged"  in l]
        ok(f"Apply complete in {time.time()-t0:.0f}s: {len(created)} created, {len(configured)} configured, {len(unchanged)} unchanged")
    else:
        warn(f"Apply had issues (exit {rc}):")
        if stderr:
            for line in stderr.strip().split("\n")[-10:]:
                warn(f"  {line}")
        if stdout:
            lines = [l for l in stdout.strip().split("\n") if l]
            ok(f"  Applied: {len(lines)} resources")

    # Wait for pods to become Running
    log(f"\nWaiting for {len(all_services)} service pods to start (this takes ~5-10 min)...")
    log("Polling every 30s until all reach Running state or 15 min timeout...")

    deadline    = time.time() + 900  # 15 min timeout
    last_counts = {}

    while time.time() < deadline:
        rc2, stdout2, _ = kubectl([
            "get", "pods", "-n", NS,
            "--no-headers",
            "-l", "managed-by=deploy-services-py",
        ])
        lines     = [l for l in stdout2.strip().split("\n") if l]
        total     = len(lines)
        running   = len([l for l in lines if "Running"    in l and "0/" not in l])
        pending   = len([l for l in lines if "Pending"    in l])
        image_pull = len([l for l in lines if "Init:"     in l or "ErrImage" in l])
        crashing  = len([l for l in lines if "CrashLoop"  in l or "Error"    in l])

        counts = {"total": total, "running": running, "pending": pending, "crashing": crashing}
        if counts != last_counts:
            log(f"  Pods: {total} total | {running} Running | {pending} Pending | {image_pull} Pulling | {crashing} Error")
            last_counts = counts

        if running >= len(all_services):
            ok(f"All {running}/{len(all_services)} service pods Running!")
            break

        if total > 0 and running + pending + image_pull + crashing < total // 2:
            warn("Many pods in unexpected state — check kubectl get pods -n exo-jtp-prod")

        time.sleep(30)
    else:
        warn(f"Timeout: {last_counts.get('running',0)}/{len(all_services)} pods Running after 15 min")
        warn("Pods may still be starting — run verification script to check")

    # Final pod count
    rc3, stdout3, _ = kubectl([
        "get", "pods", "-n", NS, "--no-headers",
        "-l", "managed-by=deploy-services-py",
    ])
    lines3   = [l for l in stdout3.strip().split("\n") if l]
    running3 = len([l for l in lines3 if "Running" in l and "0/" not in l])

    # Summary
    print(f"\n{'='*60}")
    print(f"  DEPLOYMENT SUMMARY")
    print(f"  Services deployed: {len(all_services)}")
    print(f"  Pods Running:      {running3}/{len(all_services)}")
    print(f"  Manifests saved:   {OUT_DIR}")
    print(f"{'='*60}")
    print()
    print("Next steps:")
    print("  1. Verify: kubectl get pods -n exo-jtp-prod | grep -v docker-jtp")
    print("  2. Test:   python3 -X utf8 run_service_tests_v4.py")
    print("  3. Check:  curl http://151.145.202.116:30671/api/auth_service/health")
    print()

    if running3 < len(all_services):
        sys.exit(1)


if __name__ == "__main__":
    main()
