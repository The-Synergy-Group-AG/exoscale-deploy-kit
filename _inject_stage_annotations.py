#!/usr/bin/env python3
"""
Inject gf_stage_start / gf_stage_end annotation calls around each
major stage call inside the `try:` block of deploy_pipeline.py __main__.
Run once: python3 _inject_stage_annotations.py
"""
from pathlib import Path

TARGET = Path(__file__).parent / "deploy_pipeline.py"

# ── Exact replacements: old call  →  annotated version ────────────────────────
# Each tuple is (old_text, new_text).  We match the exact indented call.
PATCHES = [
    # Stage 0 — preflight
    (
        "        stage_preflight()",
        "        gf_stage_start('0 Preflight')\n"
        "        stage_preflight()\n"
        "        gf_stage_end('0 Preflight', 'success')",
    ),
    # Stage 1 — docker build
    (
        "        stage_docker_build()",
        "        gf_stage_start('1 Docker Build', IMAGE)\n"
        "        stage_docker_build()\n"
        "        gf_stage_end('1 Docker Build', 'success', IMAGE)",
    ),
    # Stage 2 — docker push
    (
        "        stage_docker_push()",
        "        gf_stage_start('2 Docker Push', IMAGE)\n"
        "        stage_docker_push()\n"
        "        gf_stage_end('2 Docker Push', 'success', IMAGE)",
    ),
    # Stage 3b — object storage + dbaas
    (
        "        sos_info = stage_object_storage()",
        "        gf_stage_start('3b Object Storage')\n"
        "        sos_info = stage_object_storage()\n"
        "        gf_stage_end('3b Object Storage', 'success')",
    ),
    (
        "        db_info  = stage_dbaas()",
        "        gf_stage_start('3b DBaaS')\n"
        "        db_info  = stage_dbaas()\n"
        "        gf_stage_end('3b DBaaS', 'success')",
    ),
    # Stage 3 — exoscale infra (SKS cluster + nodepool)
    (
        "        kubeconfig = stage_exoscale()",
        "        gf_stage_start('3 Exoscale Infra', cfg.get('exoscale_zone',''))\n"
        "        kubeconfig = stage_exoscale()\n"
        "        gf_stage_end('3 Exoscale Infra', 'success')",
    ),
    # Stage 4 — wait for nodes
    (
        "        stage_wait_for_nodes(kubeconfig)",
        "        gf_stage_start('4 Wait Nodes')\n"
        "        stage_wait_for_nodes(kubeconfig)\n"
        "        gf_stage_end('4 Wait Nodes', 'success')",
    ),
    # Stage 4b — node labels
    (
        "        stage_sg_post_attach()\n        stage_label_nodes(kubeconfig)",
        "        stage_sg_post_attach()\n"
        "        gf_stage_start('4b Node Labels')\n"
        "        stage_label_nodes(kubeconfig)\n"
        "        gf_stage_end('4b Node Labels', 'success')",
    ),
    # Stage 5b — CSI driver
    (
        "        stage_install_csi(kubeconfig)",
        "        gf_stage_start('5b CSI Driver')\n"
        "        stage_install_csi(kubeconfig)\n"
        "        gf_stage_end('5b CSI Driver', 'success')",
    ),
    # Stage 5c — ingress + TLS
    (
        "        stage_5c_ingress_tls(kubeconfig)",
        "        gf_stage_start('5c Ingress TLS', cfg.get('ingress',{}).get('domain',''))\n"
        "        stage_5c_ingress_tls(kubeconfig)\n"
        "        gf_stage_end('5c Ingress TLS', 'success')",
    ),
    # Stage 5 — kubernetes manifests
    (
        "        stage_kubernetes(kubeconfig)",
        "        gf_stage_start('5 K8s Manifests')\n"
        "        stage_kubernetes(kubeconfig)\n"
        "        gf_stage_end('5 K8s Manifests', 'success')",
    ),
    # Stage 5d — inject secrets
    (
        "        stage_inject_secrets(kubeconfig, db_info, sos_info)",
        "        gf_stage_start('5d Inject Secrets')\n"
        "        stage_inject_secrets(kubeconfig, db_info, sos_info)\n"
        "        gf_stage_end('5d Inject Secrets', 'success')",
    ),
    # Stage 6 — verify pods
    (
        "        stage_verify(kubeconfig)",
        "        gf_stage_start('6 Verify Pods')\n"
        "        stage_verify(kubeconfig)\n"
        "        gf_stage_end('6 Verify Pods', 'success')",
    ),
    # Stage 6b — connectivity test
    (
        "        stage_connectivity_test(kubeconfig)",
        "        gf_stage_start('6b Connectivity Test')\n"
        "        stage_connectivity_test(kubeconfig)\n"
        "        gf_stage_end('6b Connectivity Test', 'success')",
    ),
    # Stage 7 — final report
    (
        "        stage_report()",
        "        gf_stage_start('7 Final Report')\n"
        "        stage_report()\n"
        "        gf_stage_end('7 Final Report', 'success', f'Image={IMAGE}')",
    ),
    # Exception handler — annotate failures
    (
        "        fail(f\"Pipeline exception: {e}\")\n"
        "        traceback.print_exc()\n"
        "        (OUT / \"deployment_report_partial.json\").write_text(json.dumps(RESULTS, indent=2))\n"
        "        pipeline_abort_cleanup()",
        "        fail(f\"Pipeline exception: {e}\")\n"
        "        gf_annotate(f\"PIPELINE EXCEPTION: {e}\", tags=['exception'], is_error=True)\n"
        "        traceback.print_exc()\n"
        "        (OUT / \"deployment_report_partial.json\").write_text(json.dumps(RESULTS, indent=2))\n"
        "        pipeline_abort_cleanup()",
    ),
]

src = TARGET.read_text(encoding="utf-8")

if src.count("gf_stage_start") > 2:
    print("Stage annotations already present — nothing to do.")
    exit(0)

applied = 0
for old, new in PATCHES:
    if old in src:
        src = src.replace(old, new, 1)
        applied += 1
    else:
        print(f"  WARN: patch target not found:\n    {old[:80]!r}")

TARGET.write_text(src, encoding="utf-8")
print(f"Applied {applied}/{len(PATCHES)} stage annotation patches.")
print(f"New file size: {len(src)} bytes")
