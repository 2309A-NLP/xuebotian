#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
SERVICE_NAME="${SERVICE_NAME:-raggd-api}"
INSTALL_SERVICE="${INSTALL_SERVICE:-0}"
START_SERVICE="${START_SERVICE:-0}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
APP_WORKERS="${APP_WORKERS:-1}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER" 2>/dev/null || id -gn)}"

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy][error] %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

ensure_python() {
  require_command "$PYTHON_BIN"
  "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required")
PY
}

ensure_virtualenv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    log "creating virtualenv at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
}

install_python_dependencies() {
  log "installing Python dependencies"
  "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
}

prepare_runtime_dirs() {
  log "preparing runtime directories"
  mkdir -p \
    "$PROJECT_DIR/data/uploads" \
    "$PROJECT_DIR/data/parsed" \
    "$PROJECT_DIR/data/images" \
    "$PROJECT_DIR/data/mineru_debug" \
    "$PROJECT_DIR/data/vision_debug" \
    "$PROJECT_DIR/data/logs" \
    "$PROJECT_DIR/data/documents"
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$PROJECT_DIR/.env.example" ]]; then
      log "creating .env from .env.example"
      cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
    else
      fail "missing $ENV_FILE and .env.example"
    fi
  fi
}

warn_if_env_missing() {
  local key="$1"
  if ! grep -Eq "^${key}=" "$ENV_FILE"; then
    log "warning: $key is not set in $ENV_FILE"
  fi
}

validate_env() {
  log "validating deployment environment"
  warn_if_env_missing "LLM_API_KEY"
  warn_if_env_missing "LLM_BASE_URL"
  warn_if_env_missing "MYSQL_HOST"
  warn_if_env_missing "MYSQL_USER"
  warn_if_env_missing "MYSQL_PASSWORD"
  warn_if_env_missing "MYSQL_DATABASE"
  warn_if_env_missing "REDIS_URL"
  warn_if_env_missing "MILVUS_URI"

  if grep -Eq '^DEBUG=true' "$ENV_FILE"; then
    log "warning: DEBUG=true is not recommended for production"
  fi
}

fix_permissions() {
  if [[ "$(id -u)" -ne 0 ]]; then
    return
  fi

  log "fixing permissions for service user ${SERVICE_USER}:${SERVICE_GROUP}"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$PROJECT_DIR/data"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$VENV_DIR"
}

write_systemd_service() {
  local service_path="/etc/systemd/system/${SERVICE_NAME}.service"
  [[ "$(id -u)" -eq 0 ]] || fail "INSTALL_SERVICE=1 requires root privileges"

  log "writing systemd service to $service_path"
  cat >"$service_path" <<EOF
[Unit]
Description=RAGgd API Service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT} --workers ${APP_WORKERS}
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"

  if [[ "$START_SERVICE" == "1" ]]; then
    log "starting systemd service"
    systemctl restart "$SERVICE_NAME"
    systemctl --no-pager --full status "$SERVICE_NAME" || true
  else
    log "systemd service installed but not started"
  fi
}

print_run_hint() {
  cat <<EOF

Deployment completed.

Project directory: $PROJECT_DIR
Virtualenv:        $VENV_DIR
Env file:          $ENV_FILE

Run in foreground:
  cd "$PROJECT_DIR"
  "$VENV_DIR/bin/uvicorn" app.main:app --host "$APP_HOST" --port "$APP_PORT" --workers "$APP_WORKERS"

Install as systemd service:
  sudo INSTALL_SERVICE=1 START_SERVICE=1 SERVICE_NAME=$SERVICE_NAME bash scripts/deploy_linux.sh
EOF
}

main() {
  require_command grep
  require_command cp
  require_command mkdir
  ensure_python
  ensure_virtualenv
  install_python_dependencies
  prepare_runtime_dirs
  ensure_env_file
  validate_env
  fix_permissions

  if [[ "$INSTALL_SERVICE" == "1" ]]; then
    require_command systemctl
    write_systemd_service
  fi

  print_run_hint
}

main "$@"
