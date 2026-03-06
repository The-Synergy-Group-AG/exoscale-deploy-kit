#!/bin/bash
set -e
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit
echo "[$(date)] Starting test rerun..." > outputs/test_rerun_log_20260306.txt
python3 run_service_tests.py \
  --kubeconfig outputs/20260306_104844/kubeconfig.yaml \
  --namespace exo-jtp-prod \
  --workers 20 \
  --output-json outputs/test_results_rerun_20260306.json \
  >> outputs/test_rerun_log_20260306.txt 2>&1
echo "[$(date)] Test rerun complete. Exit: $?" >> outputs/test_rerun_log_20260306.txt
