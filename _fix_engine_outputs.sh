#!/bin/bash
# Fix deployment engine outputs so metrics exporter sees the Run 4 manifests
# Python 3.12+ rglob() doesn't follow symlinks — use real files instead

SRC=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/k8s-manifests
DEST=/home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs/manifests/kubernetes

# Remove old symlink, create real directory, copy files
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC"/*.yaml "$DEST/" 2>/dev/null
echo "Copied $(ls "$DEST"/*.yaml 2>/dev/null | wc -l) YAML files to $DEST"

# Also copy the deployment_report as a ci_cd artifact
CI_DEST=/home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs/ci_cd_pipelines
mkdir -p "$CI_DEST"
cp /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/20260305_125732/deployment_report.json "$CI_DEST/deployment_report_20260305.json" 2>/dev/null && echo "Copied deployment_report"

echo ""
echo "Verifying exporter sees files:"
python3 -c "
from pathlib import Path
base = Path('/home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs')
manifests = sum(1 for _ in (base / 'manifests').rglob('*') if _.is_file())
cicd = sum(1 for _ in (base / 'ci_cd_pipelines').rglob('*') if _.is_file())
print(f'  manifests: {manifests}')
print(f'  ci_cd_pipelines: {cicd}')
print(f'  outputs_populated: {1 if manifests + cicd > 0 else 0}')
"
