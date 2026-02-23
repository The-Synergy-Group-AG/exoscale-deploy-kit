# AZD-005 Template Testing Checkpoint
## Exoscale Deploy Kit — Infra Provisioner Agent

**Last Updated:** 2026-02-23 20:35 CET  
**Current Status:** ✅ Phase 1 + Phase 2 + Phase 3 COMPLETE — ready for Phase 4

---

## Phase Summary

| Phase | Title | Status | Commit |
|-------|-------|--------|--------|
| Phase 1 | Infra Provisioner Agent (AZ-INFRA-001 v1.0.0) | ✅ COMPLETE | `d3a66a3` |
| Phase 2 | NATS Wiring, Secrets, CI | ✅ COMPLETE | `482a9b8` |
| Phase 3 | Orchestrator Routing, Grafana Dashboard, Alerts | ✅ COMPLETE | (this commit) |
| Phase 4 | Credentials + Live Deploy | 🔲 PENDING | — |

---

## Phase 1 Deliverables ✅

### Agent Files (`agents/infra-provisioner/`)

| File | Purpose | Tests |
|------|---------|-------|
| `template_selector.py` | T1-T7 decision matrix, CostBand, ApprovalLevel | ✅ |
| `cluster_registry.py` | JSON-backed persistent cluster state | ✅ |
| `metrics.py` | 8 Prometheus families (provision/teardown/approval/registry) | ✅ |
| `provisioner.py` | Async provision flow + Level-2/3 approval gate | ✅ |
| `teardown_manager.py` | Approval-gated teardown + registry update | ✅ |
| `infra_provisioner.py` | NATS main loop + HTTP /metrics :8118 | ✅ |
| `Dockerfile` | Python 3.11 slim, non-root, healthcheck | ✅ |
| `requirements.txt` | nats-py, prometheus_client | ✅ |
| `tests/test_infra_provisioner.py` | 38 tests — all pass | ✅ 38/38 |

### Config Updates (Phase 1)

| File | Change |
|------|--------|
| `docker-compose.prod.yml` | Added `az-infra-provisioner` service on port 8118 |
| `monitoring/prometheus.yml` | Added scrape job for `:8118` |
| `specs/agents/infra-provisioner-agent-spec.md` | Full agent specification |

---

## Phase 2 Deliverables ✅

| Item | File | Status |
|------|------|--------|
| NATS `infra` user | `communication/nats.conf` | ✅ |
| Infra secrets placeholders | `.env.prod` (gitignored) | ✅ |
| CI workflow | `.github/workflows/az-infra-provisioner-tests.yml` | ✅ |

### NATS `infra` User Permissions

```
publish:   infra.> | orchestrator.> | az.> | $JS.API.> | _INBOX.>
subscribe: infra.> | orchestrator.> | broadcast.> | az.> | _INBOX.> | _JS.ACK.>
```

---

## Phase 3 Deliverables ✅

| Item | File | Status |
|------|------|--------|
| Orchestrator infra routing | `agents/orchestrator/orchestrator.py` | ✅ |
| Prometheus alert group 8 | `monitoring/alerts.yml` | ✅ |
| Grafana dashboard d6 | `dashboards/d6-infra-provisioner.json` | ✅ |
| Phase 3 plan doc | `plans/AZD-005/PHASE_3_IMPLEMENTATION_PLAN.md` | ✅ |

### Orchestrator Routing Summary

| NATS Subject | Handler | Security Gate |
|---|---|---|
| `infra.provision` | `_handle_infra_provision` | T3+ requires `approval_token` |
| `infra.teardown` | `_handle_infra_teardown` | Always requires `approval_token` |
| `infra.status.list` | `_handle_infra_status_list` | Read-only, no gate |
| `infra.approve` | `_handle_infra_approve` | Audit logged → forwards to infra-provisioner |

### Grafana Dashboard `d6-infra-provisioner` (10 panels)

Row 1 — Stat panels: Provision Requests · Active Clusters · Approval Queue · Teardown Requests · Errors · Agent Status  
Row 2 — Time-series: Provision Duration p50/p95/p99 · Request Rates  
Row 3 — Stacked bars: Requests by Template · Approval Queue depth over time  

### Prometheus Alerts (Group 8: AZ-Infra-Provisioner)

| Alert | Threshold | Severity |
|-------|-----------|---------|
| `InfraProvisionerDown` | metric absent 2m | critical |
| `InfraProvisionErrorRate` | >0.1/s for 3m | warning |
| `InfraApprovalQueueDepthHigh` | >3 for 5m | warning |
| `InfraActiveClustersHigh` | >10 for 2m | warning |

---

## Template Tests Reference

All 7 exoscale-deploy-kit templates validated on 2026-02-23:

| Template | Status | Run File |
|----------|--------|----------|
| T1 — Minimal Test | ✅ PASS | `runs/T1-20260223.yaml` |
| T2 — Orchestrator | ✅ PASS | `runs/T2-20260223.yaml` |
| T3 — Persistent Store | ✅ PASS | `runs/T3-20260223.yaml` |
| T4 — Compute Heavy | ✅ PASS | `runs/T4-20260223.yaml` |
| T5 — Security Hardened | ✅ PASS | `runs/T5-20260223.yaml` |
| T6 — Observability | ✅ PASS | `runs/T6-20260223.yaml` |
| T7 — Full Stack Integration | ✅ PASS | `runs/T7-20260223.yaml` |

---

## Phase 4 — Next Steps (Credentials + Live Deploy)

| Priority | Item | Owner | Notes |
|----------|------|-------|-------|
| HIGH | Set real `EXO_API_KEY` / `EXO_API_SECRET` | Operator | console.exoscale.com → IAM → API Keys |
| HIGH | Rotate NATS `infra` password from placeholder | Operator | Update `nats.conf` + `.env.prod` |
| MED | Live deploy test on staging | Dev | `docker-compose up az-infra-provisioner` |
| MED | End-to-end smoke test | Dev | Send `infra.provision` with T1 → verify cluster in registry |
| LOW | Add infra panel to d1-command-centre.json | Dev | Link to d6 dashboard |
