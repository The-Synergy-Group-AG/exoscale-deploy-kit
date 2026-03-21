#!/usr/bin/env python3
"""
sg_watchdog.py — Automated SG Attachment Monitor & Remediation
===============================================================
Lesson 62: Exoscale SG Detachment — Strategic Fix

ROOT CAUSE:
  Exoscale API bugs prevent attaching SG at the instance-pool or nodepool level:
    - create_sks_nodepool(security_groups=...) → HTTP 500 (L5)
    - update_sks_nodepool(security_groups=...) → HTTP 500 (L17)
    - update_instance_pool(security_groups=...) → HTTP 403 (locked by nodepool)

  So SG is attached per-instance via attach_instance_to_security_group().
  This attachment is EPHEMERAL — when Exoscale replaces instances (maintenance,
  node cycling, infrastructure events), new instances don't inherit the SG.

SOLUTION:
  Cron-based watchdog that runs every 5 minutes:
    1. Auto-discovers current cluster, SG, and instances
    2. Checks which instances are missing the SG
    3. Reattaches SG to bare instances
    4. Verifies site health after reattachment
    5. Silent unless action taken (cron-friendly)

USAGE:
  # One-shot check + fix
  python3 sg_watchdog.py

  # Dry run (check only, no changes)
  python3 sg_watchdog.py --dry-run

  # Verbose mode (always print status)
  python3 sg_watchdog.py --verbose

  # Install cron job
  python3 sg_watchdog.py --install-cron

  # Remove cron job
  python3 sg_watchdog.py --remove-cron
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── CLI ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="SG attachment watchdog for Exoscale SKS")
parser.add_argument("--dry-run", action="store_true", help="Check only, no changes")
parser.add_argument("--verbose", action="store_true", help="Always print status")
parser.add_argument("--install-cron", action="store_true", help="Install cron job (every 5 min)")
parser.add_argument("--remove-cron", action="store_true", help="Remove cron job")
parser.add_argument("--zone", default="ch-dk-2", help="Exoscale zone")
args = parser.parse_args()

SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_FILE = SCRIPT_DIR / "outputs" / "sg_watchdog.log"
ZONE = args.zone

# ── Cron management ──────────────────────────────────────────────────────────

CRON_COMMENT = "# jtp-sg-watchdog"
CRON_CMD = (
    f"cd {SCRIPT_DIR} && "
    f"{sys.executable} {SCRIPT_DIR / 'sg_watchdog.py'} "
    f">> {LOG_FILE} 2>&1"
)
CRON_LINE = f"*/5 * * * * {CRON_CMD} {CRON_COMMENT}"


def install_cron():
    """Install cron job to run every 5 minutes."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        existing = result.stdout if result.returncode == 0 else ""

        if "jtp-sg-watchdog" in existing:
            print("Cron job already installed. Use --remove-cron to remove first.")
            return

        new_crontab = existing.rstrip() + "\n" + CRON_LINE + "\n"
        subprocess.run(
            ["crontab", "-"], input=new_crontab, text=True, check=True
        )
        print(f"Cron job installed (every 5 min)")
        print(f"  Log: {LOG_FILE}")
        print(f"  Verify: crontab -l | grep sg-watchdog")
    except Exception as e:
        print(f"Failed to install cron: {e}")
        sys.exit(1)


def remove_cron():
    """Remove the watchdog cron job."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        if result.returncode != 0 or "jtp-sg-watchdog" not in result.stdout:
            print("No sg-watchdog cron job found.")
            return

        lines = [
            ln for ln in result.stdout.splitlines()
            if "jtp-sg-watchdog" not in ln
        ]
        new_crontab = "\n".join(lines) + "\n"
        subprocess.run(
            ["crontab", "-"], input=new_crontab, text=True, check=True
        )
        print("Cron job removed.")
    except Exception as e:
        print(f"Failed to remove cron: {e}")
        sys.exit(1)


if args.install_cron:
    install_cron()
    sys.exit(0)

if args.remove_cron:
    remove_cron()
    sys.exit(0)


# ── Logging (cron-friendly: silent unless action needed) ─────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def vlog(msg):
    """Verbose log — only prints if --verbose."""
    if args.verbose:
        log(msg)


# ── Load credentials ─────────────────────────────────────────────────────────

def load_env():
    """Load .env file, handling Windows CRLF."""
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip().replace("\r", "")
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


load_env()
EXO_KEY = (os.environ.get("EXO_API_KEY") or "").strip()
EXO_SECRET = (os.environ.get("EXO_API_SECRET") or "").strip()

if not EXO_KEY or not EXO_SECRET:
    log("FATAL: EXO_API_KEY / EXO_API_SECRET not set")
    sys.exit(1)


# ── Exoscale client ──────────────────────────────────────────────────────────

try:
    from exoscale.api.v2 import Client
except ImportError:
    # Try venv
    venv_site = SCRIPT_DIR.parent / "venv" / "lib"
    for p in venv_site.glob("python*/site-packages"):
        sys.path.insert(0, str(p))
    from exoscale.api.v2 import Client

client = Client(EXO_KEY, EXO_SECRET, zone=ZONE)


# ── Auto-discovery ───────────────────────────────────────────────────────────

def discover_cluster():
    """Find the running SKS cluster, its nodepool, instances, and SG."""
    clusters = client.list_sks_clusters().get("sks-clusters", [])
    running = [c for c in clusters if c.get("state") == "running"]
    if not running:
        log("FATAL: No running SKS cluster found")
        sys.exit(1)
    if len(running) > 1:
        # Prefer cluster with 'jtp' in name
        jtp = [c for c in running if "jtp" in c.get("name", "").lower()]
        cluster = jtp[0] if jtp else running[0]
    else:
        cluster = running[0]

    cluster_id = cluster["id"]
    cluster_name = cluster["name"]
    nodepools = cluster.get("nodepools", [])

    if not nodepools:
        log(f"FATAL: Cluster {cluster_name} has no nodepools")
        sys.exit(1)

    np = nodepools[0]
    np_id = np["id"]
    np_detail = client.get_sks_nodepool(id=cluster_id, sks_nodepool_id=np_id)
    inst_pool_id = np_detail.get("instance-pool", {}).get("id")

    if not inst_pool_id:
        log(f"FATAL: Nodepool {np_id[:8]} has no instance-pool reference")
        sys.exit(1)

    pool = client.get_instance_pool(id=inst_pool_id)
    instances = pool.get("instances", [])

    # Find SG with 'jtp' in name
    sgs = client.list_security_groups().get("security-groups", [])
    jtp_sgs = [s for s in sgs if "jtp" in s.get("name", "").lower()]
    if not jtp_sgs:
        log("FATAL: No JTP security group found")
        sys.exit(1)

    sg = jtp_sgs[0]

    return {
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "nodepool_id": np_id,
        "instance_pool_id": inst_pool_id,
        "instances": instances,
        "sg_id": sg["id"],
        "sg_name": sg["name"],
        "sg_rule_count": len(sg.get("rules", [])),
    }


def check_sg_attachment(info):
    """Check which instances are missing the SG. Returns list of bare instances."""
    bare = []
    for inst in info["instances"]:
        inst_id = inst["id"]
        detail = client.get_instance(id=inst_id)
        attached_sgs = detail.get("security-groups", [])
        sg_ids = [s.get("id", "") for s in attached_sgs]
        inst_name = detail.get("name", inst_id[:8])

        if info["sg_id"] not in sg_ids:
            bare.append({"id": inst_id, "name": inst_name})
            vlog(f"  BARE: {inst_name} — SGs={[s.get('name', '?') for s in attached_sgs]}")
        else:
            vlog(f"  OK:   {inst_name} — SG attached")

    return bare


def attach_sg(info, bare_instances):
    """Attach SG to bare instances. Returns count of successful attachments."""
    attached = 0
    for inst in bare_instances:
        try:
            client.attach_instance_to_security_group(
                id=info["sg_id"], instance={"id": inst["id"]}
            )
            log(f"  ATTACHED: {inst['name']} <- {info['sg_name']}")
            attached += 1
            time.sleep(2)  # Rate limit
        except Exception as e:
            err = str(e)[:100]
            if "already" in err.lower():
                log(f"  ALREADY: {inst['name']} (race condition — OK)")
                attached += 1
            else:
                log(f"  FAILED: {inst['name']} — {err}")
    return attached


def verify_site():
    """Quick HTTP check to see if the site responds."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://jobtrackerpro.ch/health",
            headers={"User-Agent": "sg-watchdog/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    vlog(f"SG Watchdog starting (zone={ZONE})")

    # 1. Auto-discover infrastructure
    info = discover_cluster()
    vlog(
        f"Cluster: {info['cluster_name']} | "
        f"SG: {info['sg_name']} ({info['sg_rule_count']} rules) | "
        f"Instances: {len(info['instances'])}"
    )

    # 2. Check SG attachment
    bare = check_sg_attachment(info)

    if not bare:
        vlog("All instances have SG attached — no action needed")
        return

    # 3. SG detachment detected — remediate
    log(f"SG DETACHMENT DETECTED: {len(bare)}/{len(info['instances'])} instances missing {info['sg_name']}")
    for inst in bare:
        log(f"  Bare instance: {inst['name']} ({inst['id'][:12]}...)")

    if args.dry_run:
        log("DRY RUN — would reattach SG to above instances")
        return

    # 4. Reattach
    attached = attach_sg(info, bare)
    log(f"Reattached: {attached}/{len(bare)} instances")

    # 5. Verify site health
    time.sleep(5)
    if verify_site():
        log("Site health check: OK (HTTPS 200)")
    else:
        log("Site health check: FAILED — may need manual investigation")

    # 6. Summary
    log(
        f"REMEDIATION COMPLETE: "
        f"{info['sg_name']} reattached to {attached} instance(s) "
        f"on cluster {info['cluster_name']}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"WATCHDOG ERROR: {e}")
        sys.exit(1)
