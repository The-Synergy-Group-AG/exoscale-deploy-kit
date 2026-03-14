#!/usr/bin/env python3
"""
Patch deploy_pipeline.py — L39b and L46 strategic fixes.

L39B — Whitespace-strip node_count at config-load time (LESSON 39b):
  run_deploy.sh already strips node_count via tr -d '[:space:]' (shell layer).
  deploy_pipeline.py used cfg["node_count"] raw from PyYAML. While PyYAML
  parses bare integers correctly, a quoted value like node_count: ' 3 ' would
  pass in as a string with whitespace, silently breaking CPU-budget arithmetic
  (e.g. "3 " * 3700 = TypeError) and the Exoscale API size parameter.
  Fix: sanitize immediately after cfg is loaded — int(str(...).strip()).

L46 — DEPLOY_RESOURCES constant must be defined (LESSON 46):
  The pipeline tracks resources in a dict called RESULTS, but the lesson
  register documents this as DEPLOY_RESOURCES. Code uses RESULTS throughout,
  which is fine — but the constant name must exist so any future code or
  tooling that references DEPLOY_RESOURCES (per the lesson) finds it.
  Fix: add DEPLOY_RESOURCES = RESULTS alias immediately after the RESULTS dict.
"""

from pathlib import Path

DEPLOY = Path(__file__).parent / "deploy_pipeline.py"
src = DEPLOY.read_text(encoding="utf-8")
orig = src

# ── FIX 1: L39b — sanitize node_count right after cfg is loaded ──────────────
# cfg is loaded at the top of the file; node_count is first used at line ~555.
# The cleanest surgical location is right after the cfg dict is fully built,
# which is after the `cfg.update(...)` or `yaml.safe_load(...)` block.
# We add the sanitization as a one-liner after the IMAGE/IMAGE_LTS derivations.

OLD_IMAGE = (
    "IMAGE     = f\"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}\"\n"
    "IMAGE_LTS = f\"{cfg['docker_hub_user']}/{cfg['service_name']}:latest\""
)
NEW_IMAGE = (
    "IMAGE     = f\"{cfg['docker_hub_user']}/{cfg['service_name']}:{cfg['service_version']}\"\n"
    "IMAGE_LTS = f\"{cfg['docker_hub_user']}/{cfg['service_name']}:latest\"\n"
    "\n"
    "# L39b: strip whitespace from node_count — shell layer does this via tr -d;\n"
    "# deploy_pipeline.py must also sanitize so CPU-budget arithmetic and the\n"
    "# Exoscale API size parameter never receive a string with stray whitespace.\n"
    "cfg[\"node_count\"] = int(str(cfg.get(\"node_count\", 3)).strip())"
)

assert OLD_IMAGE in src, "L39b: IMAGE block not found — already patched?"
src = src.replace(OLD_IMAGE, NEW_IMAGE, 1)

# ── FIX 2: L46 — add DEPLOY_RESOURCES alias after RESULTS dict ───────────────
OLD_RESULTS_END = (
    'RESULTS = {\n'
    '    "timestamp": TS,\n'
    '    "image": IMAGE,\n'
    '    "zone": cfg["exoscale_zone"],\n'
    '    "project": cfg["project_name"],\n'
    '    "stages": {},\n'
    '    "resources": {},\n'
    '}'
)
NEW_RESULTS_END = (
    'RESULTS = {\n'
    '    "timestamp": TS,\n'
    '    "image": IMAGE,\n'
    '    "zone": cfg["exoscale_zone"],\n'
    '    "project": cfg["project_name"],\n'
    '    "stages": {},\n'
    '    "resources": {},\n'
    '}\n'
    '# L46: DEPLOY_RESOURCES must be defined — alias to RESULTS so any\n'
    '# tooling or future code referencing DEPLOY_RESOURCES finds it.\n'
    'DEPLOY_RESOURCES = RESULTS'
)

assert OLD_RESULTS_END in src, "L46: RESULTS dict not found — already patched?"
src = src.replace(OLD_RESULTS_END, NEW_RESULTS_END, 1)

DEPLOY.write_text(src, encoding="utf-8")

if src != orig:
    print("deploy_pipeline.py patched successfully (L39b + L46)")
    print("  FIX L39b: cfg['node_count'] sanitized via int(str(...).strip())")
    print("  FIX L46:  DEPLOY_RESOURCES = RESULTS alias added")
else:
    print("ERROR: no changes made")
    raise SystemExit(1)
