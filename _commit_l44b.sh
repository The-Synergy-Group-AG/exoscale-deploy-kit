#!/bin/bash
set -e
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit
git add run_service_tests.py _patch_remove_pytest_timeout.py _check_iam.py _check_lb_dns.py _cleanup_sgs.py _create_dns_zone.py _delete_ccm_keys.py _delete_sg_rules_then_sgs.py _dns_probe.py _patient_sg_delete.py _commit_msg_43.txt
git commit -m "Lesson 44b: Remove --timeout from pytest cmd (pytest-timeout not in Docker image)"
git push origin main
echo "DONE"
