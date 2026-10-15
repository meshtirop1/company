#!/usr/bin/env bash
#
# Back up the database (manage.py backup_db). Run nightly by cron as the deploy user -
# see deploy/cron.d/shinhe-backup - and usable by hand:
#   /home/deploy/sites/shinhe/deploy/backup.sh [label]
#
# Copies land in /home/deploy/sites/shinhe/backups/ as db-<date>-<time>-<label>.sqlite3.gz,
# readable only by the deploy user, kept for 14 days (the newest 5 always stay).
#
# To restore one (as root):
#   systemctl stop shinhe
#   cp /home/deploy/sites/shinhe/db.sqlite3 /home/deploy/sites/shinhe/db.sqlite3.before-restore
#   gunzip -c /home/deploy/sites/shinhe/backups/<file>.sqlite3.gz > /home/deploy/sites/shinhe/db.sqlite3
#   chown deploy:deploy /home/deploy/sites/shinhe/db.sqlite3
#   systemctl start shinhe

set -euo pipefail

APP_DIR="/home/deploy/sites/shinhe"
ENV_FILE="$APP_DIR/env"
LABEL="${1:-nightly}"

cd "$APP_DIR"
. "$APP_DIR/deploy/load_env.sh"
mkdir -p backups
{
  printf '%s ' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  .venv/bin/python manage.py backup_db --label "$LABEL"
} >> backups/backup.log 2>&1
