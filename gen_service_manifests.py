#!/usr/bin/env python3
"""
gen_service_manifests.py — Plan 125: Generate per-service K8s YAML manifests
=============================================================================
Reads services_manifest.json (219 services), reads each service's config.json
for resource specifications, and generates one Kubernetes YAML file per service.

Each YAML contains:
  - Deployment  (replicas=1, SERVICE_NAME env var, port 8000, probes)
  - Service     (ClusterIP, port 8000)

Resource specs are read from service/services/{name}/config.json.
Replicas are ALWAYS 1 regardless of config.json value (Plan 125: single-user).

Usage:
    python3 gen_service_manifests.py --dry-run          # validate only
    python3 gen_service_manifests.py \\
        --output-dir ./outputs/20260305_120000/k8s-services \\
        --image iandrewitz/docker-jtp:9 \\
        --namespace exo-jtp-prod

Plan: 125-True-Microservices-Deployment
Phase: 1 — Service Manifest Generator
Created: 2026-03-05
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# ── Resource defaults (fallback if config.json missing) ──────────────────────
RESOURCE_FALLBACK: dict[str, str] = {
    "cpu_request":    "10m",
    "memory_request": "64Mi",
    "cpu_limit":      "500m",
    "memory_limit":   "256Mi",
}

# Tier overrides for services without individual config.json resource keys
RESOURCE_TIERS: dict[str, dict[str, str]] = {
    "small":  {"cpu_request": "10m",  "memory_request": "64Mi",  "cpu_limit": "200m",  "memory_limit": "256Mi"},
    "medium": {"cpu_request": "10m", "memory_request": "128Mi", "cpu_limit": "500m",  "memory_limit": "512Mi"},
    "large":  {"cpu_request": "10m", "memory_request": "256Mi", "cpu_limit": "1000m", "memory_limit": "1Gi"},
}

# Script location — all paths are relative to the exoscale-deploy-kit directory
SCRIPT_DIR = Path(__file__).parent
MANIFEST_PATH = SCRIPT_DIR / "service" / "services_manifest.json"
SERVICES_DIR = SCRIPT_DIR / "service" / "services"

# L46: deploy-time safe resource defaults (see L43 for rationale).
# Requests are kept small so all 219 services fit a 3-node cluster.
# Limits are generous — individual services may burst, but won't starve others.
DEPLOY_RESOURCES: dict = {
    "cpu_request":    "10m",
    "memory_request": "64Mi",
    "cpu_limit":      "500m",
    "memory_limit":   "256Mi",
}


def to_dns_name(service_name: str) -> str:
    """Convert service filesystem name to K8s DNS-compatible name.

    Rules:
      - Replace underscores with hyphens
      - Convert to lowercase
      - Truncate to 63 characters (K8s DNS label limit)
      - Strip leading/trailing hyphens

    Args:
        service_name: Service name as found in services_manifest.json

    Returns:
        DNS-safe Kubernetes resource name
    """
    dns = service_name.lower().replace("_", "-")
    dns = re.sub(r"[^a-z0-9-]", "-", dns)
    dns = dns[:63].rstrip("-")
    return dns


def load_service_resources(service_name: str) -> dict[str, str]:
    """Return deploy-time safe resource spec for a service.

    LESSON 43: The service engine generates config.json with production-grade
    requests (cpu_request: "250m", memory_request: "512Mi").  Trusting those
    values saturates a 3-node test cluster after ~61 pods.

    Fix: requests are ALWAYS overridden to DEPLOY_RESOURCES safe values
    (10m CPU / 64Mi memory).  Limits are preserved from config.json when
    present so individual services can still burst up to their allocation.

    Args:
        service_name: Filesystem name of the service directory

    Returns:
        Dict with keys: cpu_request, memory_request, cpu_limit, memory_limit
    """
    # Always start from deploy-time safe requests
    result = DEPLOY_RESOURCES.copy()

    config_path = SERVICES_DIR / service_name / "config.json"
    if not config_path.exists():
        return result

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return result

    # Preserve limits from service config (generous limits are fine)
    # but NEVER trust the service-engine cpu_request/memory_request —
    # those are production-scale values, not test-cluster values.
    if "cpu_limit" in cfg:
        result["cpu_limit"] = str(cfg["cpu_limit"])
    if "memory_limit" in cfg:
        result["memory_limit"] = str(cfg["memory_limit"])

    return result


def render_yaml(
    service_name: str,
    dns_name: str,
    image: str,
    namespace: str,
    resources: dict[str, str],
) -> str:
    """Render the Kubernetes YAML for one service (Deployment + Service).

    Args:
        service_name: Filesystem name used as SERVICE_NAME env var value
        dns_name: DNS-safe name used for K8s resource metadata
        image: Full Docker image reference (e.g. iandrewitz/docker-jtp:9)
        namespace: Kubernetes namespace
        resources: Dict with cpu_request, memory_request, cpu_limit, memory_limit

    Returns:
        YAML string containing Deployment and Service separated by ---
    """
    return f"""\
---
# Plan 125: {service_name}
# Generated by gen_service_manifests.py
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {dns_name}
  namespace: {namespace}
  labels:
    app: {dns_name}
    plan: "125"
    version: "9"
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0
  selector:
    matchLabels:
      app: {dns_name}
  template:
    metadata:
      labels:
        app: {dns_name}
        plan: "125"
    spec:
      imagePullSecrets:
        - name: dockerhub-creds
      containers:
        - name: {dns_name}
          image: {image}
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
              protocol: TCP
          env:
            - name: SERVICE_NAME
              value: "{service_name}"
          envFrom:
            - configMapRef:
                name: jtp-gateway-config
                optional: true
            - secretRef:
                name: ai-api-keys
                optional: true
          resources:
            requests:
              cpu: "{resources['cpu_request']}"
              memory: "{resources['memory_request']}"
            limits:
              cpu: "{resources['cpu_limit']}"
              memory: "{resources['memory_limit']}"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 30
            failureThreshold: 3
            timeoutSeconds: 5
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
            timeoutSeconds: 5
          securityContext:
            readOnlyRootFilesystem: false
            allowPrivilegeEscalation: false
---
apiVersion: v1
kind: Service
metadata:
  name: {dns_name}
  namespace: {namespace}
  labels:
    app: {dns_name}
    plan: "125"
spec:
  selector:
    app: {dns_name}
  ports:
    - port: 8000
      targetPort: 8000
      protocol: TCP
  type: ClusterIP
---
# L66 Tier 3: HPA auto-scaling (FADS Part 5)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {dns_name}-hpa
  namespace: {namespace}
  labels:
    app: {dns_name}
    plan: "125"
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {dns_name}
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
"""


# ── L72: AI Backend Services — First-Class Factory Citizens ──────────────────
# These 12 services provide real GPT-4 + Pinecone intelligence.
# They're deployed alongside the 219 generated services using the same Docker
# image but with SERVICE_PORT set to their native port.
AI_BACKEND_SERVICES: list[dict] = [
    {"name": "gpt4_orchestrator",   "dns": "gpt4-orchestrator",   "port": 8032, "source": "shared/ai/gpt4_orchestrator"},
    {"name": "claude_integration",  "dns": "claude-integration",  "port": 8033, "source": "shared/ai/claude_integration"},
    {"name": "embeddings_engine",   "dns": "embeddings-engine",   "port": 8034, "source": "shared/ai/embeddings_engine"},
    {"name": "vector_store",        "dns": "vector-store",        "port": 8035, "source": "shared/ai/vector_store"},
    {"name": "job_matcher",         "dns": "job-matcher",         "port": 8019, "source": "shared/extended/job_matcher"},
    {"name": "cv_processor",        "dns": "cv-processor",        "port": 8020, "source": "shared/extended/cv_processor"},
    {"name": "career_navigator",    "dns": "career-navigator",    "port": 8017, "source": "shared/extended/career_navigator"},
    {"name": "skill_bridge",        "dns": "skill-bridge",        "port": 8018, "source": "shared/extended/skill_bridge"},
    {"name": "memory_system",       "dns": "memory-system",       "port": 8009, "source": "shared/consciousness/memory_system"},
    {"name": "learning_system",     "dns": "learning-system",     "port": 8010, "source": "shared/consciousness/learning_system"},
    {"name": "pattern_recognition", "dns": "pattern-recognition", "port": 8011, "source": "shared/consciousness/pattern_recognition"},
    {"name": "decision_making",     "dns": "decision-making",     "port": 8012, "source": "shared/consciousness/decision_making"},
]


def render_ai_backend_yaml(
    svc: dict,
    image: str,
    namespace: str,
) -> str:
    """Render K8s YAML for an AI backend service (Deployment + Service).

    AI backends differ from generated services:
      - They use their native SERVICE_PORT (not 8000)
      - They get ai-api-keys secret for OpenAI/Pinecone credentials
      - They have slightly higher resource limits (AI workloads)
    """
    name = svc["name"]
    dns = svc["dns"]
    port = svc["port"]
    return f"""\
---
# L72: AI Backend Service — {name}
# Generated by gen_service_manifests.py (AI backend integration)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {dns}
  namespace: {namespace}
  labels:
    app: {dns}
    category: ai-backend
    plan: "l72"
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0
  selector:
    matchLabels:
      app: {dns}
  template:
    metadata:
      labels:
        app: {dns}
        category: ai-backend
        plan: "l72"
    spec:
      imagePullSecrets:
        - name: dockerhub-creds
      containers:
        - name: {dns}
          image: {image}
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: {port}
              protocol: TCP
          env:
            - name: SERVICE_NAME
              value: "{name}"
            - name: SERVICE_PORT
              value: "{port}"
          envFrom:
            - configMapRef:
                name: jtp-gateway-config
                optional: true
            - secretRef:
                name: ai-api-keys
                optional: true
          resources:
            requests:
              cpu: "10m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: {port}
            initialDelaySeconds: 120
            periodSeconds: 30
            failureThreshold: 3
            timeoutSeconds: 5
          readinessProbe:
            httpGet:
              path: /health
              port: {port}
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
            timeoutSeconds: 5
          securityContext:
            readOnlyRootFilesystem: false
            allowPrivilegeEscalation: false
---
apiVersion: v1
kind: Service
metadata:
  name: {dns}
  namespace: {namespace}
  labels:
    app: {dns}
    category: ai-backend
    plan: "l72"
spec:
  selector:
    app: {dns}
  ports:
    - port: {port}
      targetPort: {port}
      protocol: TCP
  type: ClusterIP
"""


def generate_manifests(
    output_dir: Path,
    image: str,
    namespace: str,
    dry_run: bool,
) -> int:
    """Main manifest generation loop.

    Reads services_manifest.json, generates one YAML per service, writes to
    output_dir (or validates only in dry_run mode).

    Args:
        output_dir: Directory to write YAML files into
        image: Docker image reference for all service pods
        namespace: Kubernetes namespace
        dry_run: If True, validate and print without writing

    Returns:
        Exit code: 0 = success, 1 = error
    """
    if not MANIFEST_PATH.exists():
        print(f"ERROR: services_manifest.json not found at {MANIFEST_PATH}", file=sys.stderr)
        return 1

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Failed to load services_manifest.json: {exc}", file=sys.stderr)
        return 1

    services: list[str] = manifest.get("services", [])
    if not services:
        print("ERROR: No services found in services_manifest.json", file=sys.stderr)
        return 1

    generation = manifest.get("generation", "unknown")
    total = manifest.get("total", len(services))
    print(f"[gen_service_manifests] Generation: {generation}")
    print(f"[gen_service_manifests] Services:   {len(services)} of {total} declared")
    print(f"[gen_service_manifests] Image:       {image}")
    print(f"[gen_service_manifests] Namespace:  {namespace}")
    print(f"[gen_service_manifests] Output dir: {output_dir}")
    print(f"[gen_service_manifests] Dry-run:    {dry_run}")
    print()

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    written = 0

    for svc_name in services:
        dns = to_dns_name(svc_name)
        resources = load_service_resources(svc_name)
        yaml_content = render_yaml(svc_name, dns, image, namespace, resources)

        if dry_run:
            # Validate YAML is parseable
            try:
                import yaml  # type: ignore[import]
                list(yaml.safe_load_all(yaml_content))
            except Exception as exc:
                errors.append(f"{svc_name}: YAML parse error: {exc}")
                continue
            print(f"  OK  {dns:<60} ({resources['memory_request']} → {resources['memory_limit']})")
        else:
            out_file = output_dir / f"{dns}.yaml"
            try:
                out_file.write_text(yaml_content, encoding="utf-8")
                written += 1
            except OSError as exc:
                errors.append(f"{svc_name}: write error: {exc}")

    # ── L72: Generate manifests for AI backend services ────────────────────
    ai_written = 0
    print(f"[gen_service_manifests] L72: Generating {len(AI_BACKEND_SERVICES)} AI backend manifests...")
    for svc in AI_BACKEND_SERVICES:
        yaml_content = render_ai_backend_yaml(svc, image, namespace)
        if dry_run:
            try:
                import yaml  # type: ignore[import]
                list(yaml.safe_load_all(yaml_content))
            except Exception as exc:
                errors.append(f"AI:{svc['name']}: YAML parse error: {exc}")
                continue
            print(f"  OK  {svc['dns']:<60} (AI backend, port {svc['port']})")
        else:
            out_file = output_dir / f"{svc['dns']}.yaml"
            try:
                out_file.write_text(yaml_content, encoding="utf-8")
                ai_written += 1
                written += 1
            except OSError as exc:
                errors.append(f"AI:{svc['name']}: write error: {exc}")
    if not dry_run:
        print(f"[gen_service_manifests] L72: {ai_written} AI backend YAML files written")

    print()
    if dry_run:
        ok_count = len(services) + len(AI_BACKEND_SERVICES) - len(errors)
        total_expected = len(services) + len(AI_BACKEND_SERVICES)
        print(f"[gen_service_manifests] DRY-RUN: {ok_count}/{total_expected} valid")
    else:
        total_expected = len(services) + len(AI_BACKEND_SERVICES)
        print(f"[gen_service_manifests] Written:  {written}/{total_expected} YAML files → {output_dir}")

    if errors:
        print(f"\n[gen_service_manifests] ERRORS ({len(errors)}):")
        for err in errors:
            print(f"  ERR {err}")
        return 1

    return 0


def main() -> None:
    """Entry point — parse CLI arguments and run manifest generation."""
    parser = argparse.ArgumentParser(
        description=(
            "Plan 125: Generate per-service Kubernetes YAML manifests "
            "for 219 JTP microservices."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "outputs" / "k8s-services",
        help="Directory to write YAML files (default: outputs/k8s-services/)",
    )
    parser.add_argument(
        "--image",
        default="iandrewitz/docker-jtp:9",
        help="Docker image reference (default: iandrewitz/docker-jtp:9)",
    )
    parser.add_argument(
        "--namespace",
        default="exo-jtp-prod",
        help="Kubernetes namespace (default: exo-jtp-prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifests without writing to disk",
    )

    args = parser.parse_args()
    exit_code = generate_manifests(
        output_dir=args.output_dir,
        image=args.image,
        namespace=args.namespace,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
