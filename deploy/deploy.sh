#!/usr/bin/env bash
#
# Idempotent re-deploy. Run on the server (or via SSH from CI):
#   /home/deploy/shinhe_backend/deploy/deploy.sh
#
# Pulls the latest master, installs deps, runs migrations + collectstatic,
# and restarts gunicorn. Bails out on any error.

set -euo pipefail

APP_DIR="/home/deploy/shinhe_backend"
ENV_FILE="/etc/shinhe-company.env"
BRANCH="${BRANCH:-master}"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

cd "$APP_DIR"

log "Pulling latest from $BRANCH"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

log "Installing/updating dependencies"
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

log "Loading env and running Django steps"
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy || true

log "Restarting gunicorn"
sudo /bin/systemctl restart shinhe-company
sudo /bin/systemctl status shinhe-company --no-pager | head -10 || true

log "Deploy complete: $(git rev-parse --short HEAD)"
