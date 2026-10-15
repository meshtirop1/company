# Sourced by deploy.sh and backup.sh: export the app's env file the way systemd's
# EnvironmentFile reads it (KEY=value lines, optional quotes) - parsed, never executed.
set -a
while IFS= read -r line; do
  case "$line" in ''|\#*) continue ;; esac
  [ "${line#*=}" = "$line" ] && continue
  key="${line%%=*}"; val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  export "$key=$val"
done < "$ENV_FILE"
set +a
