#!/bin/bash
# Fix deployment engine K8s Manifests counter
# Point the engine outputs/manifests/kubernetes at ALL Run 4 output YAMLs

# Run 4 has 6 gateway manifests in k8s-manifests/ 
# AND service manifests spread in outputs/
# Use the full outputs/20260305_125732 dir as source (includes k8s-manifests + any subfolders)

OUTPUTS_DIR=/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs
ENGINE_MANIFESTS=/home/iandre/projects/jtp-bio-v3/engines/deployment_engine/outputs/manifests/kubernetes

mkdir -p "$(dirname "$ENGINE_MANIFESTS")"
rm -rf "$ENGINE_MANIFESTS"

# Symlink to the full Run 4 output directory so all YAML files are counted
ln -sf "$OUTPUTS_DIR/20260305_125732" "$ENGINE_MANIFESTS"

echo "Symlink: $ENGINE_MANIFESTS -> $OUTPUTS_DIR/20260305_125732"
echo "YAML files visible to exporter:"
python3 -c "from pathlib import Path; p=Path('$ENGINE_MANIFESTS'); print(sum(1 for f in p.rglob('*.yaml') if f.is_file()))"

echo ""
echo "Current deployment_engine_output_manifests value:"
curl -s http://localhost:8005/metrics 2>/dev/null | grep output_manifests
