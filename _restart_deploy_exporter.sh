#!/bin/bash
# Restart deployment engine exporter to pick up new symlink
pkill -f "engines/deployment_engine/inputs/metrics_exporter.py" 2>/dev/null
sleep 2
cd /home/iandre/projects/jtp-bio-v3
nohup python3 engines/deployment_engine/inputs/metrics_exporter.py > /tmp/deploy_exporter.log 2>&1 &
echo "Exporter restarted PID: $!"
sleep 4
echo "Manifests metric:"
curl -s http://localhost:8005/metrics 2>/dev/null | grep output_manifests
echo ""
echo "Outputs populated:"
curl -s http://localhost:8005/metrics 2>/dev/null | grep outputs_populated
