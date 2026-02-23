# AZD-005 Template Testing Checkpoint
## Exoscale Deploy Kit — Infra Provisioner Agent

**Last Updated:** 2026-02-23 20:22 CET  
**Current Status:** ✅ Phase 1 + Phase 2 COMPLETE — ready for Phase 3

---

## Phase Summary

| Phase | Title | Status | Commit |
|-------|-------|--------|--------|
| Phase 1 | Infra Provisioner Agent (AZ-INFRA-001 v1.0.0) | ✅ COMPLETE | `d3a66a3` |
| Phase 2 | NATS Wiring, Secrets, CI | ✅ COMPLETE | `482a9b8` |
| Phase 3 | Orchestrator Routing + Live Deploy | 🔲 PENDING | — |

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
| Phase 2 plan doc | `plans/AZD-005/PHASE_2_IMPLEMENTATION_PLAN.md` | ✅ |

### NATS `infra` User Permissions

```
publish:   infra.> | orchestrator.> | az.> | $JS.API.> | _INBOX.>
subscribe: infra.> | orchestrator.> | broadcast.> | az.> | _INBOX.> | _JS.ACK.>
```

---

## Template Tests Reference

All 7 exoscale-deploy-kit templates were validated on 2026-02-23:

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

## Phase 3 — Next Steps

| Priority | Item | Notes |
|----------|------|-------|
| HIGH | Wire `infra.*` into orchestrator task routing | `orchestrator.py` subject table |
| HIGH | Set real EXO credentials in Vault + `.env.prod` | `console.exoscale.com → IAM → API Keys` |
| MED | Grafana panel for infra-provisioner | Add to `d1-command-centre.json` |
| MED | Live deploy test on staging | `docker-compose up az-infra-provisioner` |
| LOW | Rotate NATS `infra` password from placeholder | Update both `nats.conf` + `.env.prod` |
