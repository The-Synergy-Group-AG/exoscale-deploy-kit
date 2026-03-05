#!/usr/bin/env python3
"""
Inject Grafana real-time annotation helper into deploy_pipeline.py
immediately after the section() logging helper definition.
Run once: python3 _inject_grafana.py
"""
from pathlib import Path

TARGET = Path(__file__).parent / "deploy_pipeline.py"

GRAFANA_BLOCK = '''

# =============================================================================
#  GRAFANA REAL-TIME ANNOTATION HELPER
#  Plan 123-P5+: Pushes stage events as annotations to localhost Grafana so the
#  jtp-deployment-dashboard shows a live timeline of the deployment progress.
#  Non-fatal: if Grafana is unreachable the pipeline continues unaffected.
# =============================================================================
import urllib.request as _urllib_req
import urllib.error   as _urllib_err
import base64         as _base64

_GF_ENV_FILE = Path(__file__).parent.parent / "monitoring" / "grafana" / ".env"


def _load_gf_env() -> dict:
    """Parse monitoring/grafana/.env for GRAFANA_URL / USER / PASSWORD."""
    env: dict = {}
    if _GF_ENV_FILE.exists():
        for line in _GF_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


_GF_CFG  = _load_gf_env()
_GF_URL  = _GF_CFG.get("GRAFANA_URL",      "http://localhost:3000")
_GF_USER = _GF_CFG.get("GRAFANA_USER",     "admin")
_GF_PASS = _GF_CFG.get("GRAFANA_PASSWORD", "admin")


def gf_annotate(text: str, tags: list | None = None, is_error: bool = False) -> None:
    """
    Push a deployment-stage annotation to the local Grafana instance.
    Non-fatal: errors are logged as WARNs and pipeline continues.
    """
    try:
        if tags is None:
            tags = []
        base_tags = ["deployment", "jtp", cfg.get("project_name", "jtp"), TS]
        all_tags  = list(dict.fromkeys(base_tags + tags + (["error"] if is_error else [])))
        prefix    = "[FAIL] " if is_error else "[OK] "
        payload   = json.dumps({
            "text":  prefix + text,
            "tags":  all_tags,
            "time":  int(datetime.now().timestamp() * 1000),
        }).encode("utf-8")
        creds = _base64.b64encode(f"{_GF_USER}:{_GF_PASS}".encode()).decode()
        req   = _urllib_req.Request(
            f"{_GF_URL.rstrip('/')}/api/annotations",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Basic {creds}",
            },
            method="POST",
        )
        with _urllib_req.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                log(f"[Grafana] Annotation: {text[:70]}")
    except Exception as _exc:
        warn(f"[Grafana] Annotation skipped (non-fatal): {_exc}")


def gf_stage_start(stage: str, detail: str = "") -> None:
    """Annotate Grafana at the START of a pipeline stage."""
    msg = f"STAGE {stage} -- START"
    if detail:
        msg += f" | {detail}"
    gf_annotate(msg, tags=[f"stage:{stage.lower().replace(' ', '_')}"])


def gf_stage_end(stage: str, status: str = "success", detail: str = "") -> None:
    """Annotate Grafana at the END of a pipeline stage."""
    is_err = status.lower() in ("fail", "failed", "error")
    msg    = f"STAGE {stage} -- {status.upper()}"
    if detail:
        msg += f" | {detail}"
    gf_annotate(msg,
                tags=[f"stage:{stage.lower().replace(' ', '_')}", status.lower()],
                is_error=is_err)

'''

ANCHOR = "def section(s): print(f\"\\n{'='*60}\\n  {s}\\n{'='*60}\")"

src = TARGET.read_text(encoding="utf-8")

if "def gf_annotate" in src:
    print("Already patched — nothing to do.")
else:
    # Find the anchor line and insert the block right after it
    idx = src.find(ANCHOR)
    if idx == -1:
        # Try a simpler anchor
        ANCHOR2 = "def section(s):"
        idx = src.find(ANCHOR2)
        if idx == -1:
            print("ERROR: Could not locate anchor line. Manual patch required.")
            exit(1)
        # Find end of that line
        end_of_line = src.find("\n", idx)
    else:
        end_of_line = src.find("\n", idx)

    new_src = src[:end_of_line + 1] + GRAFANA_BLOCK + src[end_of_line + 1:]
    TARGET.write_text(new_src, encoding="utf-8")
    print(f"Patched: inserted Grafana annotation helper after line containing '{ANCHOR[:40]}...'")
    print(f"New file size: {len(new_src)} bytes")
