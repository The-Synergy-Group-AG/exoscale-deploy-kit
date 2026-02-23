# Exoscale Deploy Kit — Template Registry
> **Agent-facing index** — pick your template, replace `YYYYMMDD`, deploy.

---

## Quick-Pick Decision Tree

```
Do you need persistent state (DB / block storage)?
├── NO  → Do you need to test quickly / cheaply?
│         ├── YES → T1-minimal-test        (stateless, single node, ~$0.02/hr)
│         └── NO  → Is this a security/RBAC test?
│                   ├── YES → T5-security-hardened  (~$0.10/hr)
│                   └── NO  → T2-orchestrator        (Redis, 2 nodes, ~$0.12/hr)
└── YES → What kind of workload?
          ├── Document/scoring state       → T3-persistent-store  (~$0.18/hr)
          ├── Heavy analytics / profiling  → T4-compute-heavy     (~$0.60/hr)
          ├── Monitoring / Grafana stack   → T6-observability     (~$0.35/hr)
          └── Full suite integration test  → T7-full-stack        (~$0.55/hr)
```

---

## Template Reference

### T1 — Minimal Test
| Field | Value |
|---|---|
| **File** | `templates/T1-minimal-test.yaml` |
| **Purpose** | Fastest spin-up for stateless CI/preflight checks |
| **Agents** | QA Agent, any dry-run validation |
| **Nodes** | 1× tiny (1vCPU / 512MB) |
| **DB** | ❌ |
| **SOS** | ❌ |
| **Block Storage** | ❌ |
| **Autoscaling** | ❌ |
| **Est. cost** | ~$0.02/hr |
| **Deploy time** | ~4 min |
| **Namespace** | `exo-stargate-test` |

```bash
python3 deploy_pipeline.py --config templates/T1-minimal-test.yaml --auto
```

---

### T2 — Orchestrator
| Field | Value |
|---|---|
| **File** | `templates/T2-orchestrator.yaml` |
| **Purpose** | Agent-to-agent message routing, Redis pub/sub, circuit breaker testing |
| **Agents** | Orchestrator, Feature Coordinator, Circuit Breaker, Rate Limiter |
| **Nodes** | 2× small (2vCPU / 2GB) |
| **DB** | ✅ Redis 7 |
| **SOS** | ❌ |
| **Block Storage** | ❌ |
| **Autoscaling** | ✅ 2→8 replicas |
| **Est. cost** | ~$0.12/hr |
| **Deploy time** | ~8 min |
| **Namespace** | `exo-stargate-orch` |

```bash
python3 deploy_pipeline.py --config templates/T2-orchestrator.yaml --auto
```

---

### T3 — Persistent Store
| Field | Value |
|---|---|
| **File** | `templates/T3-persistent-store.yaml` |
| **Purpose** | Durable state: document index, scoring history, knowledge graph |
| **Agents** | Librarian Agent, Performance Manager Agent |
| **Nodes** | 2× small (2vCPU / 2GB) |
| **DB** | ✅ PostgreSQL 16 |
| **SOS** | ✅ private (`state`) |
| **Block Storage** | ✅ 10GB at `/data` |
| **Autoscaling** | ✅ 2→6 replicas |
| **Est. cost** | ~$0.18/hr |
| **Deploy time** | ~10 min |
| **Namespace** | `exo-stargate-store` |

```bash
python3 deploy_pipeline.py --config templates/T3-persistent-store.yaml --auto
```

---

### T4 — Compute Heavy
| Field | Value |
|---|---|
| **File** | `templates/T4-compute-heavy.yaml` |
| **Purpose** | Data-intensive profiling, optimisation analysis, model inference |
| **Agents** | Data Analyst Agent (PerformanceProfiler, OptimizationAnalyzer, WorkflowOptimizer) |
| **Nodes** | 3× large (4vCPU / 8GB) |
| **DB** | ✅ PostgreSQL 16 |
| **SOS** | ✅ private (`analytics`) |
| **Block Storage** | ✅ 100GB at `/data` |
| **Autoscaling** | ✅ 2→15 replicas |
| **Est. cost** | ~$0.60/hr |
| **Deploy time** | ~12 min |
| **Namespace** | `exo-stargate-compute` |

```bash
python3 deploy_pipeline.py --config templates/T4-compute-heavy.yaml --auto
```

---

### T5 — Security Hardened
| Field | Value |
|---|---|
| **File** | `templates/T5-security-hardened.yaml` |
| **Purpose** | Isolated RBAC/policy testing, code audits, zero public exposure |
| **Agents** | Security Agent (CodeAuditor, RBACRegistry, PolicyEnforcer, SecurityScanner) |
| **Nodes** | 2× small (2vCPU / 2GB) |
| **DB** | ❌ (stateless) |
| **SOS** | ❌ (no exfil surface) |
| **Block Storage** | ❌ |
| **Autoscaling** | ✅ 2→4 replicas (hard ceiling) |
| **Est. cost** | ~$0.10/hr |
| **Deploy time** | ~7 min |
| **Namespace** | `exo-stargate-security` |

```bash
python3 deploy_pipeline.py --config templates/T5-security-hardened.yaml --auto
```

---

### T6 — Observability Stack
| Field | Value |
|---|---|
| **File** | `templates/T6-observability.yaml` |
| **Purpose** | Grafana + Prometheus + Loki stack, health checks, predictive monitoring |
| **Agents** | System Monitor Agent (HealthChecker, MetricsCollector, AlertRouter, PredictiveMonitor) |
| **Nodes** | 2× medium (2vCPU / 4GB) |
| **DB** | ✅ PostgreSQL 16 (Grafana datasource) |
| **SOS** | ✅ private (`telemetry`) |
| **Block Storage** | ✅ 50GB at `/data` (Loki + Prometheus WAL) |
| **Autoscaling** | ✅ 2→6 replicas |
| **Est. cost** | ~$0.35/hr |
| **Deploy time** | ~12 min |
| **Namespace** | `exo-stargate-obs` |
| **K8s port** | 3000 (Grafana) |

```bash
python3 deploy_pipeline.py --config templates/T6-observability.yaml --auto
```

---

### T7 — Full Stack Integration
| Field | Value |
|---|---|
| **File** | `templates/T7-full-stack-integration.yaml` |
| **Purpose** | Production-equivalent E2E test — all agents, all services, all paths |
| **Agents** | ALL — full StarGate suite working in concert |
| **Nodes** | 3× medium (2vCPU / 4GB) |
| **DB** | ✅ PostgreSQL 16 |
| **SOS** | ✅ private (`integration`) |
| **Block Storage** | ✅ 50GB at `/data` |
| **Autoscaling** | ✅ 3→20 replicas |
| **Est. cost** | ~$0.55/hr |
| **Deploy time** | ~15 min |
| **Namespace** | `exo-stargate-integration` |

```bash
python3 deploy_pipeline.py --config templates/T7-full-stack-integration.yaml --auto
```

---

## Cost Comparison Summary

| Template | $/hr est. | Nodes | Node Size | DB | SOS | Block |
|---|---|---|---|---|---|---|
| T1 Minimal | ~$0.02 | 1 | tiny | ❌ | ❌ | ❌ |
| T2 Orchestrator | ~$0.12 | 2 | small | Redis | ❌ | ❌ |
| T3 Persistent Store | ~$0.18 | 2 | small | PG 16 | ✅ 10GB | ✅ 10GB |
| T4 Compute Heavy | ~$0.60 | 3 | large | PG 16 | ✅ | ✅ 100GB |
| T5 Security Hardened | ~$0.10 | 2 | small | ❌ | ❌ | ❌ |
| T6 Observability | ~$0.35 | 2 | medium | PG 16 | ✅ | ✅ 50GB |
| T7 Full Stack | ~$0.55 | 3 | medium | PG 16 | ✅ | ✅ 50GB |

> **Always run `python3 teardown.py --force` when done** — resources are billed per minute.

---

## Naming Convention

All templates use `project_name: stargate-tN-YYYYMMDD`.  
Replace `YYYYMMDD` with today's date before deploying:

```yaml
# Example for T3 deployed on 2026-02-23:
project_name: stargate-t3-20260223
```

This ensures every deployment is uniquely identifiable and resources can be discovered/torn down by date.

---

## Zone Options

All templates default to `ch-dk-2` (Zurich). Change to `ch-gva-2` (Geneva) for:
- Geneva-specific compliance requirements
- Redundancy testing across zones
- Latency comparison benchmarks

---

---

## Test Run History — 2026-02-23

| Template | Deployment ID | Cluster ID | Nodes | Duration | Result | Teardown Report |
|----------|--------------|------------|-------|----------|--------|-----------------|
| T1-minimal-test | 20260223_T1 | (deleted) | 1x small | ~4 min | ✅ PASS | Clean |
| T2-orchestrator | 20260223_T2 | (deleted) | 2x small | ~5 min | ✅ PASS | Clean |
| T3-persistent-store | 20260223_T3 | (deleted) | 2x small | ~8 min | ✅ PASS | ⚠️ DBaaS leftover (fixed) |
| T4-compute-heavy | 20260223_152615 | d922a55e | 3x large | ~7 min | ✅ PASS | teardown_report_20260223_160455.json |
| T5-security-hardened | 20260223_162157 | 5f29c216 | 2x small | ~5 min | ✅ PASS | teardown_report_20260223_163137.json |
| T6-observability | 20260223_164621 | 3996c9c5 | 2x medium | ~6.5 min | ✅ PASS | teardown_report_20260223_165330.json |
| T7-full-stack-integration | 20260223_165416 | f2bd5856 | 3x medium | ~7.75 min | ✅ PASS | teardown_report_20260223_174046.json |

> Full session analysis: `../SUMMARY-20260223.md`

---

## Known Issues (2026-02-23)

| # | Issue | Affected | Workaround |
|---|-------|---------|------------|
| L22 | Windows UnicodeEncodeError | All | Use `python -X utf8` flag |
| L23 | SG per-instance 404 — nodepool SG not attached | T4–T7 | Manual SG in console; fix: use `update_sks_nodepool` |
| L24 | DBaaS leftover on teardown | T3 (pre-fix) | Fixed in teardown.py — confirmed clean T4+ |
| L25 | `cd && python` path on Windows CMD | All | Use full absolute path to script |

---

*Last updated: 2026-02-23 | exoscale-deploy-kit templates v1.0*
