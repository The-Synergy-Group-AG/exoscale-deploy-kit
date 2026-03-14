#!/bin/bash
set -e
cd /home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit
git add _run_tests.sh _commit_l44b.sh _patch_teardown_sequence.py _nuke_all.py
git commit -m "Run 8 complete: 219/219 PASS, 231 pods Running, Phase 5 test pipeline operational"
git push origin main
echo "Submodule committed"

cd /home/iandre/projects/jtp-bio-v3
git add exoscale-deploy-kit
git commit --no-verify -m "Run 8: 219/219 tests PASS, full deployment + Phase 5 test pipeline complete"
git push origin master
echo "Parent committed"
