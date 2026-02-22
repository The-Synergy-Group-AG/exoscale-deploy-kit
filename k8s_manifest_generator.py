#!/usr/bin/env python3
"""
Exoscale Deploy Kit — Kubernetes Manifest Generator
====================================================
Generates parametrised Kubernetes YAML manifests for deployment to Exoscale SKS.

Generated manifests (in --outputs-dir):
  00-namespace.yaml        — Kubernetes Namespace
  01-deployment.yaml       — Deployment (non-root, readiness/liveness probes, imagePullSecrets)
  02-service.yaml          — LoadBalancer Service (NLB auto-provisioned by cloud controller)
  03-hpa.yaml              — HorizontalPodAutoscaler (CPU 70% / Memory 80%)
  04-network-policy.yaml   — NetworkPolicy (ingress/egress restrictions)
  05-resource-quota.yaml   — ResourceQuota (namespace-level limits)

NodePort note (LESSON 7):
  Exoscale default Security Group pre-approves NodePorts: 30671, 30888, 30999
  Use one of these (--nodeport default: 30671) or add custom SG rules for others.

Usage:
  python3 k8s_manifest_generator.py \\
    --service-name my-service \\
    --image myuser/my-service:1.0.0 \\
    --namespace my-project-production \\
    --port 5000 \\
    --nodeport 30671 \\
    --outputs-dir ./outputs/20260222_120000/k8s-manifests
"""
import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Kubernetes manifests for Exoscale SKS deployment"
    )
    parser.add_argument("--service-name",  required=True,         help="Service/deployment name")
    parser.add_argument("--image",         required=True,         help="Full Docker image reference (user/name:tag)")
    parser.add_argument("--version",       default="1.0.0",       help="Service version label")
    parser.add_argument("--namespace",     default="default",     help="Kubernetes namespace")
    parser.add_argument("--replicas",      type=int, default=2,   help="Number of pod replicas")
    parser.add_argument("--port",          type=int, default=5000,help="Container port (internal, app listens here)")
    parser.add_argument("--service-port",  type=int, default=None,help="K8s service port (defaults to --port)")
    parser.add_argument(
        "--nodeport", type=int, default=30671,
        help=(
            "NodePort for direct node access (default: 30671). "
            "LESSON 7: Use a pre-approved Exoscale NodePort (30671, 30888, 30999) "
            "or add custom SG rules."
        ),
    )
    parser.add_argument("--outputs-dir",   required=True,         help="Directory to write manifest files")
    args = parser.parse_args()

    out          = Path(args.outputs_dir)
    out.mkdir(parents=True, exist_ok=True)
    svc          = args.service_name
    ns           = args.namespace
    service_port = args.service_port if args.service_port else args.port

    # ── 00: Namespace ──────────────────────────────────────────────────────
    (out / "00-namespace.yaml").write_text(f"""apiVersion: v1
kind: Namespace
metadata:
  name: {ns}
  labels:
    app.kubernetes.io/managed-by: exoscale-deploy-kit
    environment: production
""")

    # ── 01: Deployment ─────────────────────────────────────────────────────
    (out / "01-deployment.yaml").write_text(f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {svc}
  namespace: {ns}
  labels:
    app: {svc}
    version: "{args.version}"
spec:
  replicas: {args.replicas}
  selector:
    matchLabels:
      app: {svc}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app: {svc}
        version: "{args.version}"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      imagePullSecrets:
      - name: dockerhub-creds
      containers:
      - name: {svc}
        image: {args.image}
        imagePullPolicy: Always
        ports:
        - containerPort: {args.port}
          protocol: TCP
        env:
        - name: ENVIRONMENT
          value: "production"
        - name: SERVICE_NAME
          value: "{svc}"
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        readinessProbe:
          httpGet:
            path: /health
            port: {args.port}
          initialDelaySeconds: 10
          periodSeconds: 10
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /health
            port: {args.port}
          initialDelaySeconds: 30
          periodSeconds: 30
          failureThreshold: 3
""")

    # ── 02: Service ────────────────────────────────────────────────────────
    # LESSON 6: type: LoadBalancer triggers Exoscale cloud controller to auto-create NLB
    # LESSON 7: nodePort {args.nodeport} must be pre-approved in Exoscale default SG
    (out / "02-service.yaml").write_text(f"""apiVersion: v1
kind: Service
metadata:
  name: {svc}
  namespace: {ns}
  labels:
    app: {svc}
  annotations:
    # Exoscale cloud controller uses this annotation to name the auto-created NLB
    service.beta.kubernetes.io/exoscale-loadbalancer-name: "{svc}-nlb"
spec:
  # LESSON 6: type: LoadBalancer causes Exoscale cloud controller to auto-create NLB
  # Do NOT create the NLB manually — this annotation handles it.
  type: LoadBalancer
  selector:
    app: {svc}
  ports:
  - name: http
    port: 80
    targetPort: {args.port}
    # LESSON 7: NodePort {args.nodeport} is pre-approved in Exoscale default SG
    nodePort: {args.nodeport}
    protocol: TCP
  - name: api
    port: {service_port}
    targetPort: {args.port}
    protocol: TCP
  - name: https
    port: 443
    targetPort: {args.port}
    protocol: TCP
""")

    # ── 03: HPA ────────────────────────────────────────────────────────────
    (out / "03-hpa.yaml").write_text(f"""apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {svc}-hpa
  namespace: {ns}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {svc}
  minReplicas: 2
  maxReplicas: 10
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
""")

    # ── 04: Network Policy ─────────────────────────────────────────────────
    (out / "04-network-policy.yaml").write_text(f"""apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {svc}-netpol
  namespace: {ns}
spec:
  podSelector:
    matchLabels:
      app: {svc}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - ports:
    - port: {args.port}
      protocol: TCP
  egress:
  - ports:
    - port: 443
      protocol: TCP
    - port: 80
      protocol: TCP
    - port: 53
      protocol: UDP
""")

    # ── 05: Resource Quota ─────────────────────────────────────────────────
    (out / "05-resource-quota.yaml").write_text(f"""apiVersion: v1
kind: ResourceQuota
metadata:
  name: {ns}-quota
  namespace: {ns}
spec:
  hard:
    pods: "20"
    requests.cpu: "4"
    requests.memory: "4Gi"
    limits.cpu: "8"
    limits.memory: "8Gi"
""")

    manifests = sorted(out.glob("*.yaml"))
    print(f"✅ Generated {len(manifests)} Kubernetes manifests in {out}")
    for m in manifests:
        print(f"   📄 {m.name}")
    sys.exit(0)


if __name__ == "__main__":
    main()
