#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sg_remediate.py — Emergency SG Fix for live cluster
=====================================================
Plan 122-DEH ISSUE-001 / ISSUE-026 (SG empty + not attached)

ROOT CAUSE ANALYSIS:
  1. ISSUE-026 (NEW): deploy_pipeline.py creates the SG but NEVER adds rules.
     Exoscale shows warning: "This Group is empty — applied to a VM it will have
     no effect." An empty SG has NO inbound/outbound rules → useless.

  2. ISSUE-001 (KNOWN): SG attachment via attach_instance_to_security_group()
     returned 404 while instances were still provisioning. The old pipeline had
     5-attempt retry that ran TOO EARLY. stage_sg_post_attach() fixes the timing
     but the SG RULES must be populated FIRST.

FIX (this script):
  Step 1 — Populate the SG with the rules required for SKS worker nodes:
    - TCP 10250 in (kubelet API — kubectl logs/exec/port-forward)
    - TCP 10255 in (read-only kubelet metrics)
    - TCP 30000-32767 in (NodePort services, covers 30671/30888/30999)
    - TCP 443 in (HTTPS)
    - TCP 80 in (HTTP)
    - TCP + UDP intra-SG (pod-to-pod, CNI Calico, konnectivity proxy)
    - ICMP in (ping, NLB health checks)
    - TCP + UDP + ICMP egress to 0.0.0.0/0 (unrestricted outbound)

  Step 2 — Attach the populated SG to all 3 worker node instances.
    (Nodes are Ready now, so the compute API reports them — no 404.)

FUTURE PREVENTION:
  deploy_pipeline.py stage_exoscale() now calls _populate_sg_rules(c, sg_id)
  immediately after create_security_group(). See LESSON 25 in deploy_pipeline.py.

Usage:
  cd exoscale-deploy-kit
  python3 -X utf8 sg_remediate.py
  python3 -X utf8 sg_remediate.py --dry-run  # preview rules without applying
"""
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# ─── CLI ──────────────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="Populate and attach empty SG for live cluster")
_parser.add_argument("--dry-run", action="store_true", help="Preview rules without applying")
_parser.add_argument(
    "--sg-id",      default="ea4863f0-1719-11f1-9b26-650e2dd397f1",
    help="Security Group ID (default: current cluster SG)"
)
_parser.add_argument(
    "--cluster-id", default="841a92ab-74cf-4904-82fa-53960855cf1c",
    help="SKS Cluster ID (default: current cluster)"
)
_parser.add_argument(
    "--pool-id",    default="faca3270-6019-4655-8486-2fe273120dfa",
    help="Node Pool ID (default: current pool)"
)
_parser.add_argument("--zone", default="ch-dk-2", help="Exoscale zone")
_args = _parser.parse_args()

# ─── Logging ──────────────────────────────────────────────────────────────────
def log(msg):   print(f"[{datetime.now().strftime('%H:%M:%S')}]  {msg}")
def ok(msg):    print(f"[{datetime.now().strftime('%H:%M:%S')}] OK {msg}")
def warn(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] WARN {msg}")
def fail(msg):  print(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL {msg}")

# ─── Load credentials ─────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# .strip() removes CRLF (\r\n) if .env was created on Windows (LESSON 22 CRLF issue)
EXO_KEY    = (os.environ.get("EXO_API_KEY") or "").strip()
EXO_SECRET = (os.environ.get("EXO_API_SECRET") or "").strip()
if not EXO_KEY or not EXO_SECRET:
    fail("EXO_API_KEY / EXO_API_SECRET not set in .env or environment")
    sys.exit(1)

SG_ID      = _args.sg_id
CLUSTER_ID = _args.cluster_id
POOL_ID    = _args.pool_id
ZONE       = _args.zone

# ─── SKS Worker Node SG Rules ─────────────────────────────────────────────────
# Based on Exoscale SKS documentation + battle-tested best practice.
# LESSON 25: These rules MUST be added to the SG before it is attached to nodes.
#
# Reference: https://community.exoscale.com/documentation/sks/quick-start/
# Reference: Exoscale support confirmation — empty SG = no-op (confirmed 2026-03-03)
#
# Rule structure (Exoscale Python SDK v0.16+ keyword args):
#   flow_direction : "ingress" | "egress"
#   protocol       : "tcp" | "udp" | "icmp" | "icmpv6" | "esp" | "ah" | "gre"
#   network        : CIDR string, e.g. "0.0.0.0/0"  (mutually exclusive with security_group)
#   security_group : {"id": sg_id}                   (mutually exclusive with network)
#   start_port     : int 1-65535 (TCP/UDP only)
#   end_port       : int 1-65535 (TCP/UDP only)
#   icmp_type      : int -1=any  (ICMP only)
#   icmp_code      : int -1=any  (ICMP only)
#   description    : str (shown in Exoscale console)

SKS_NODE_SG_RULES = [
    # ── Inbound: Kubelet ──────────────────────────────────────────────────
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 10250, "end_port": 10250,
        "description": "Kubelet API — kubectl logs/exec/port-forward (CRITICAL)"
    },
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 10255, "end_port": 10255,
        "description": "Kubelet read-only metrics"
    },
    # ── Inbound: NodePort services ────────────────────────────────────────
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 30000, "end_port": 32767,
        "description": "NodePort services 30000-32767 (incl. 30671 gateway, 30888, 30999)"
    },
    # ── Inbound: HTTP/HTTPS ───────────────────────────────────────────────
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 80, "end_port": 80,
        "description": "HTTP (NLB health check + direct access)"
    },
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 443, "end_port": 443,
        "description": "HTTPS (NLB health check + direct access)"
    },
    # ── Inbound: Intra-cluster (CNI + pod-to-pod + konnectivity) ─────────
    # Source = same SG → only traffic from OTHER nodes in the same pool
    {
        "flow_direction": "ingress", "protocol": "tcp",
        "security_group": {"id": SG_ID},
        "start_port": 1, "end_port": 65535,
        "description": "Intra-cluster TCP (Calico CNI, konnectivity, pod-to-pod)"
    },
    {
        "flow_direction": "ingress", "protocol": "udp",
        "security_group": {"id": SG_ID},
        "start_port": 1, "end_port": 65535,
        "description": "Intra-cluster UDP (Calico VXLAN UDP 4789, WireGuard 51820-51821)"
    },
    # ── Inbound: ICMP ─────────────────────────────────────────────────────
    # NOTE: Exoscale SDK does NOT accept icmp_type/icmp_code — omit them
    # to allow all ICMP types (ping, unreachable, etc.)
    {
        "flow_direction": "ingress", "protocol": "icmp",
        "network": "0.0.0.0/0",
        "description": "ICMP ingress (ping, NLB health probes)"
    },
    # ── Egress: unrestricted (nodes need internet for image pulls, DNS, etc.) ──
    {
        "flow_direction": "egress", "protocol": "tcp",
        "network": "0.0.0.0/0",
        "start_port": 1, "end_port": 65535,
        "description": "Egress all TCP (Docker Hub, DNS, Exoscale API)"
    },
    {
        "flow_direction": "egress", "protocol": "udp",
        "network": "0.0.0.0/0",
        "start_port": 1, "end_port": 65535,
        "description": "Egress all UDP (DNS port 53, NTP port 123)"
    },
    {
        "flow_direction": "egress", "protocol": "icmp",
        "network": "0.0.0.0/0",
        "description": "Egress ICMP"
    },
]

# ─── DRY RUN ──────────────────────────────────────────────────────────────────
if _args.dry_run:
    print(f"\n{'='*60}")
    print(f"  DRY RUN — No changes will be made")
    print(f"  SG: {SG_ID}")
    print(f"  Zone: {ZONE}")
    print(f"{'='*60}")
    print(f"\nRules that WOULD be added ({len(SKS_NODE_SG_RULES)} total):")
    for i, r in enumerate(SKS_NODE_SG_RULES, 1):
        src = r.get("network", f"SG:{r.get('security_group', {}).get('id', '?')[:8]}")
        port = f":{r.get('start_port','*')}-{r.get('end_port','*')}" if "start_port" in r else ""
        print(f"  {i:2}. {r['flow_direction']:8} {r['protocol']:5} {src}{port} — {r['description']}")
    print(f"\nStep 2: Attach SG to all instances in pool {POOL_ID[:8]}...")
    print(f"\nRun without --dry-run to apply.")
    sys.exit(0)

# ─── CONNECT ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  SG REMEDIATE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  SG: {SG_ID[:8]}... ({ZONE})")
print(f"{'='*60}\n")

from exoscale.api.v2 import Client
c = Client(EXO_KEY, EXO_SECRET, zone=ZONE)
log(f"Connected to Exoscale zone: {ZONE}")

# ─── STEP 1: ADD RULES ────────────────────────────────────────────────────────
print(f"\n--- Step 1: Populate SG {SG_ID[:8]}... with {len(SKS_NODE_SG_RULES)} rules ---")

_rules_ok   = 0
_rules_fail = 0
_rules_skip = 0

for _rule in SKS_NODE_SG_RULES:
    _desc  = _rule["description"]
    _proto = _rule["protocol"]
    _dir   = _rule["flow_direction"]
    _src   = _rule.get("network", f"SG:{_rule.get('security_group', {}).get('id','?')[:8]}")
    _port  = f":{_rule.get('start_port','*')}-{_rule.get('end_port','*')}" if "start_port" in _rule else ""

    try:
        c.add_rule_to_security_group(id=SG_ID, **_rule)
        ok(f"  {_dir:8} {_proto:5} {_src}{_port} — {_desc}")
        _rules_ok += 1
    except Exception as _e:
        _err = str(_e)[:80]
        if "already exists" in _err.lower() or "duplicate" in _err.lower():
            log(f"  {_dir:8} {_proto:5} {_src}{_port} — SKIP (rule exists): {_desc}")
            _rules_skip += 1
        else:
            warn(f"  {_dir:8} {_proto:5} {_src}{_port} — FAILED: {_err}")
            _rules_fail += 1

print()
if _rules_ok > 0 or _rules_skip > 0:
    ok(f"SG rules: {_rules_ok} added, {_rules_skip} already-existed (skipped), {_rules_fail} failed")
else:
    warn(f"All {len(SKS_NODE_SG_RULES)} rules failed! Check credentials and SG ID.")
    sys.exit(1)

# ─── STEP 2: ATTACH SG TO INSTANCES ──────────────────────────────────────────
print(f"\n--- Step 2: Attach SG to node-pool instances ---")

_MAX_ATTACH_ATTEMPTS = 3
_ATTACH_RETRY_DELAY  = 10

try:
    _cluster    = c.get_sks_cluster(id=CLUSTER_ID)
    _pool       = next((p for p in _cluster.get("nodepools", []) if p.get("id") == POOL_ID), {})
    _ip_id      = _pool.get("instance-pool", {}).get("id")
    if not _ip_id:
        warn("instance-pool ref not found in nodepool — cannot attach SG")
        sys.exit(1)

    _ip         = c.get_instance_pool(id=_ip_id)
    _instances  = _ip.get("instances", [])
    log(f"Found {len(_instances)} instances in pool {_ip_id[:8]}...")

    _attached   = 0
    _failed_ids = []

    for _inst in _instances:
        _inst_id   = _inst.get("id")
        _inst_name = _inst.get("name", _inst_id[:8])
        _success   = False

        for _attempt in range(1, _MAX_ATTACH_ATTEMPTS + 1):
            try:
                c.attach_instance_to_security_group(id=SG_ID, instance={"id": _inst_id})
                ok(f"  SG attached to {_inst_name} (attempt {_attempt})")
                _attached += 1
                _success = True
                break
            except Exception as _e:
                _err = str(_e)[:80]
                if "already" in _err.lower():
                    ok(f"  {_inst_name} already has SG attached — OK")
                    _attached += 1
                    _success = True
                    break
                warn(f"  {_inst_name} attempt {_attempt}/{_MAX_ATTACH_ATTEMPTS}: {_err}")
                if _attempt < _MAX_ATTACH_ATTEMPTS:
                    time.sleep(_ATTACH_RETRY_DELAY)

        if not _success:
            _failed_ids.append(_inst_name)

    print()
    if _attached == len(_instances):
        ok(f"All {_attached}/{len(_instances)} instances now have SG attached")
    elif _attached > 0:
        warn(f"Partial: {_attached}/{len(_instances)} instances attached. Failed: {_failed_ids}")
    else:
        warn(f"SG attachment failed for ALL instances: {_failed_ids}")
        warn("Manual fix: Exoscale Console → Compute → Instances → <each node> → Security Groups → Attach")

except Exception as _e:
    warn(f"Step 2 error: {_e}")
    warn("Manual fix: Exoscale Console → Compute → Instances → <each node> → Security Groups → Attach")

# ─── SUMMARY ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  REMEDIATION COMPLETE")
print(f"  SG: {SG_ID}")
print(f"  Rules added: {_rules_ok}  |  Skipped (existing): {_rules_skip}  |  Failed: {_rules_fail}")
print(f"  Instances attached: {_attached}/{len(_instances) if '_instances' in dir() else '?'}")
print(f"{'='*60}")
print()
print("Verification:")
print(f"  1. Exoscale Console → Security Groups → jtp-test1-sg-165856 → should show {_rules_ok + _rules_skip} rules")
print(f"  2. Exoscale Console → Compute → Instances → <node> → Security Groups → should show jtp-test1-sg-165856")
print(f"  3. kubectl logs <pod> -n exo-jtp-prod → should work (port 10250 now open)")
print()
