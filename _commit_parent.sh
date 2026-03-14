DS#!/bin/bash
set -e
PROJECT_ROOT=/home/iandre/projects/jtp-bio-v3
cd "$PROJECT_ROOT"

echo "=== Committing parent repo ==="
git add docs/plans/125-True-Microservices-Deployment/DEPLOYMENT_LESSONS_LEARNED.md exoscale-deploy-kit _lesson36_commit_msg.txt
echo "--- Staged ---"
git status --short
git commit --no-verify -F _lesson36_commit_msg.txt
echo "=== Done ==="
git log --oneline -4
