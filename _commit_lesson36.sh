#!/bin/bash
set -e
PROJECT_ROOT=/home/iandre/projects/jtp-bio-v3

# ── Step 1: Commit inside exoscale-deploy-kit submodule ──────
echo "=== Committing in exoscale-deploy-kit submodule ==="
cd "$PROJECT_ROOT/exoscale-deploy-kit"
git add \
  run_deploy.sh \
  _post_deploy_monitoring.sh \
  _fix_engine_outputs.sh \
  _fix_manifests_symlink.sh \
  _restart_deploy_exporter.sh \
  _deploy_ksm.sh \
  _add_lesson36.py \
  _commit_lesson36.sh
git status --short
git commit -F "$PROJECT_ROOT/_lesson36_commit_msg.txt" || echo "[INFO] Nothing new to commit in submodule"
git log --oneline -2

# ── Step 2: Commit inside engines/deployment_engine submodule (if any) ───────
ENGINE_DIR="$PROJECT_ROOT/engines/deployment_engine"
if [ -d "$ENGINE_DIR/.git" ] || git -C "$ENGINE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    echo ""
    echo "=== Committing in engines/deployment_engine submodule ==="
    cd "$ENGINE_DIR"
    git add outputs/ 2>/dev/null || true
    CHANGED=$(git status --short | wc -l)
    if [ "$CHANGED" -gt 0 ]; then
        git commit -m "Run 4 outputs: 6 gateway manifests + deployment_report synced (Lesson 36)"
        git log --oneline -2
    else
        echo "[INFO] Nothing to commit in engines/deployment_engine"
    fi
fi

# ── Step 3: Commit parent repo (docs + submodule pointer updates) ──────────
echo ""
echo "=== Committing parent repo ==="
cd "$PROJECT_ROOT"
git add \
  docs/plans/125-True-Microservices-Deployment/DEPLOYMENT_LESSONS_LEARNED.md \
  _lesson36_commit_msg.txt \
  exoscale-deploy-kit \
  engines/deployment_engine 2>/dev/null || true
git status --short
git commit -F _lesson36_commit_msg.txt || echo "[INFO] Nothing new to commit in parent"
echo "=== Done ==="
git log --oneline -3
