# StarGate Template Test Plan
**Version:** 1.0 | **Date:** 2026-02-23 | **Zone:** ch-dk-2

> Each template is deployed, validated, and torn down sequentially.
> Results saved to `templates/test-results/TN-result-YYYYMMDD.json`.

---

## Test Protocol

### Lifecycle per Template
```
1. Update project_name with today's date → templates/runs/TN-YYYYMMDD.yaml
2. python3 deploy_pipeline.py --config templates/runs/TN-YYYYMMDD.yaml --auto
3. python3 templates/template_test_runner.py --config templates/runs/TN-YYYYMMDD.yaml
4. Results saved → templates/test-results/TN-result-YYYYMMDD.json
5. Human reviews results → confirms teardown
6. python3 teardown.py --force
7. Proceed to next template
```

---

## Universal Test Checks (All Templates)

| ID | Check | Method | Pass Criteria |
|---|---|---|---|
| U01 | Deploy pipeline exits 0 | `deploy_pipeline.py` return code | exit code == 0 |
| U02 | Cluster exists in Exoscale | Exoscale API | cluster name matches `project_name` |
| U03 | All nodes Ready | `kubectl get nodes` | all nodes STATUS=Ready |
| U04 | Correct node count | `kubectl get nodes` | count == `node_count` in config |
| U05 | Correct node type | Exoscale API | node type matches `node_type_size` |
| U06 | Namespace exists | `kubectl get ns` | namespace == `k8s_namespace` |
| U07 | Service running | `kubectl get svc -n <ns>` | service exists, correct port |
| U08 | Node labels applied | `kubectl get nodes --show-labels` | all `stargate.io/*` labels present |
| U09 | Template tag visible | `kubectl get nodes --show-labels` | `stargate.io/template` matches TN |
| U10 | No credential leak in config | File scan | no secrets in YAML |

---

## Template-Specific Test Checks

### T1 — Minimal Test

| ID | Check | Pass Criteria |
|---|---|---|
| T1-01 | Node type is `tiny` | node type == standard.tiny |
| T1-02 | Single node only | node_count == 1 |
| T1-03 | No DB provisioned | no DBaaS service named `{project_name}` |
| T1-04 | No SOS bucket | no SOS bucket `{project_slug}-test` |
| T1-05 | No PVC/block storage | no PVC in namespace |
| T1-06 | No HPA | no HorizontalPodAutoscaler in namespace |
| T1-07 | Namespace = `exo-stargate-test` | exact match |
| T1-08 | NodePort 30001 reachable | netcat/curl to nodeport |

---

### T2 — Orchestrator

| ID | Check | Pass Criteria |
|---|---|---|
| T2-01 | Node type is `small` | standard.small |
| T2-02 | 2 worker nodes | count == 2 |
| T2-03 | Redis DBaaS exists | service type == redis |
| T2-04 | Redis connection string in K8s secret | secret `db-credentials` exists |
| T2-05 | No SOS bucket | SOS disabled |
| T2-06 | No block storage PVC | no PVC |
| T2-07 | HPA exists | min=2, max=8 |
| T2-08 | Namespace = `exo-stargate-orch` | exact match |
| T2-09 | NLB exists | load balancer created |
| T2-10 | NodePort 30002 assigned | service config correct |

---

### T3 — Persistent Store

| ID | Check | Pass Criteria |
|---|---|---|
| T3-01 | Node type is `small` | standard.small |
| T3-02 | 2 worker nodes | count == 2 |
| T3-03 | PostgreSQL 16 DBaaS exists | service type == pg, version 16 |
| T3-04 | DB secret injected | secret `db-credentials` in namespace |
| T3-05 | SOS bucket exists | bucket `{slug}-state` exists |
| T3-06 | SOS secret injected | secret `sos-credentials` in namespace |
| T3-07 | PVC exists and Bound | PVC status == Bound, size == 10Gi |
| T3-08 | PVC mounted at `/data` | pod spec has correct mountPath |
| T3-09 | HPA exists | min=2, max=6 |
| T3-10 | Namespace = `exo-stargate-store` | exact match |

---

### T4 — Compute Heavy

| ID | Check | Pass Criteria |
|---|---|---|
| T4-01 | Node type is `large` | standard.large |
| T4-02 | 3 worker nodes | count == 3 |
| T4-03 | PostgreSQL 16 DBaaS exists | service type == pg |
| T4-04 | SOS bucket `{slug}-analytics` exists | bucket accessible |
| T4-05 | PVC 100GB exists and Bound | size == 100Gi, status == Bound |
| T4-06 | HPA min=2 max=15 | autoscaler configured |
| T4-07 | CPU limit = 2000m per pod | resource limits match |
| T4-08 | Memory limit = 4Gi per pod | resource limits match |
| T4-09 | PDB min_available = 2 | PodDisruptionBudget exists |
| T4-10 | Namespace = `exo-stargate-compute` | exact match |

---

### T5 — Security Hardened

| ID | Check | Pass Criteria |
|---|---|---|
| T5-01 | Node type is `small` | standard.small |
| T5-02 | 2 worker nodes | count == 2 |
| T5-03 | No DB provisioned | no DBaaS service |
| T5-04 | No SOS bucket | no SOS bucket |
| T5-05 | No block storage PVC | no PVC |
| T5-06 | CPU limit = 500m | hard limit enforced |
| T5-07 | Memory limit = 512Mi | hard limit enforced |
| T5-08 | HPA max = 4 (hard ceiling) | max_replicas == 4 |
| T5-09 | TLS ingress only | ingress tls: true |
| T5-10 | Namespace = `exo-stargate-security` | isolated namespace |
| T5-11 | `stargate.io/clearance: restricted` label | node label present |

---

### T6 — Observability

| ID | Check | Pass Criteria |
|---|---|---|
| T6-01 | Node type is `medium` | standard.medium |
| T6-02 | 2 worker nodes | count == 2 |
| T6-03 | PostgreSQL 16 DBaaS exists | service type == pg |
| T6-04 | SOS bucket `{slug}-telemetry` exists | bucket accessible |
| T6-05 | PVC 50GB exists and Bound | size == 50Gi |
| T6-06 | Service port = 3000 (Grafana) | k8s_port == 3000 |
| T6-07 | NodePort 30006 assigned | correct port mapping |
| T6-08 | Memory limit = 2Gi | headroom for Loki + Prometheus |
| T6-09 | metrics-server addon running | kubectl top nodes responds |
| T6-10 | Namespace = `exo-stargate-obs` | exact match |

---

### T7 — Full Stack Integration

| ID | Check | Pass Criteria |
|---|---|---|
| T7-01 | Node type is `medium` | standard.medium |
| T7-02 | 3 worker nodes | count == 3 |
| T7-03 | PostgreSQL 16 DBaaS exists | service type == pg |
| T7-04 | SOS bucket `{slug}-integration` exists | bucket accessible |
| T7-05 | PVC 50GB exists and Bound | size == 50Gi |
| T7-06 | HPA min=3 max=20 | full autoscale range |
| T7-07 | PDB min_available = 2 | rolling update protection |
| T7-08 | NLB + Ingress + TLS | full networking stack |
| T7-09 | All secrets injected | db-credentials + sos-credentials |
| T7-10 | Namespace = `exo-stargate-integration` | exact match |
| T7-11 | All node labels correct | `stargate.io/agents: all` label |

---

## Success Criteria Summary

| Template | Min Pass Rate | Critical Checks |
|---|---|---|
| T1 | 100% (8/8) | U01, U03, T1-01, T1-03 |
| T2 | 90% (9/10) | U01, U03, T2-03, T2-04 |
| T3 | 90% (9/10) | U01, U03, T3-03, T3-07 |
| T4 | 85% (8.5/10) | U01, U03, T4-01, T4-05 |
| T5 | 100% (11/11) | U01, T5-06, T5-07, T5-09 |
| T6 | 90% (9/10) | U01, U03, T6-05, T6-06 |
| T7 | 90% (10/11) | U01, U03, T7-03, T7-07, T7-08 |

---

## Result Storage

Results saved as:
```
templates/test-results/
  T1-result-20260223.json
  T2-result-20260223.json
  ...
  T7-result-20260223.json
  SUMMARY-20260223.md
```

---

## Test Runner Usage

```bash
# Run tests for a specific template after deploy:
python3 templates/template_test_runner.py --config templates/runs/T1-20260223.yaml

# Output: templates/test-results/T1-result-20260223.json
```
