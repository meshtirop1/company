#!/usr/bin/env bash
#
# Idempotent re-deploy. Run on the server (or via SSH from CI):
#   /home/deploy/sites/shinhe/deploy/deploy.sh
#
# Pulls the latest master, installs deps, runs migrations + collectstatic,
# and restarts gunicorn. Bails out on any error.

set -euo pipefail

APP_DIR="/home/deploy/sites/shinhe"
ENV_FILE="$APP_DIR/env"
BRANCH="${BRANCH:-master}"
SERVICE="shinhe"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

cd "$APP_DIR"

log "Pulling latest from $BRANCH"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

log "Installing/updating dependencies"
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

log "Loading env (systemd EnvironmentFile style; parsed, not sourced)"
set -a
while IFS= read -r line; do
  case "$line" in ''|\#*) continue ;; esac
  [ "${line#*=}" = "$line" ] && continue
  key="${line%%=*}"; val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  export "$key=$val"
done < "$ENV_FILE"
set +a

log "Running Django steps"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy || true

log "Restarting gunicorn"
sudo /usr/bin/systemctl restart "$SERVICE"
sudo /usr/bin/systemctl is-active "$SERVICE" || true

log "Deploy complete: $(git rev-parse --short HEAD)"
