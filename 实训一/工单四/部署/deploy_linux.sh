#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-rag-qa-system}"
APP_DIR="${APP_DIR:-/opt/rag-qa-system}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
SERVICE_NAME="${SERVICE_NAME:-rag-qa}"
SERVICE_USER="${SERVICE_USER:-$USER}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
VECTOR_BACKEND="${VECTOR_BACKEND:-milvus}"
ENABLE_MILVUS="${ENABLE_MILVUS:-1}"
MILVUS_DIR="${MILVUS_DIR:-/opt/milvus-standalone}"
INSTALL_SYSTEM_PACKAGES="${INSTALL_SYSTEM_PACKAGES:-1}"
INSTALL_PYTHON_DEPS="${INSTALL_PYTHON_DEPS:-1}"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

log() {
  printf '[deploy] %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

replace_or_append_env() {
  local file="$1"
  local key="$2"
  local value="$3"
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

install_system_packages() {
  if [[ "$INSTALL_SYSTEM_PACKAGES" != "1" ]]; then
    log "Skip system package installation"
    return
  fi

  require_cmd apt-get
  log "Installing system packages"
  sudo apt-get update
  sudo apt-get install -y \
    git \
    curl \
    unzip \
    build-essential \
    pkg-config \
    libgl1 \
    libglib2.0-0 \
    "$PYTHON_BIN" \
    "${PYTHON_BIN}-venv"
}

prepare_app_dir() {
  if [[ ! -d "$APP_DIR" ]]; then
    echo "APP_DIR does not exist: $APP_DIR" >&2
    echo "Please upload or clone the project to the target directory first." >&2
    exit 1
  fi
}

setup_venv() {
  require_cmd "$PYTHON_BIN"
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip setuptools wheel

  if [[ "$INSTALL_PYTHON_DEPS" == "1" ]]; then
    log "Installing Python dependencies"
    pip install -r "$APP_DIR/requirements.txt"
  else
    log "Skip Python dependency installation"
  fi
}

prepare_runtime_dirs() {
  log "Preparing runtime directories"
  mkdir -p \
    "$APP_DIR/data/uploads" \
    "$APP_DIR/data/parsed" \
    "$APP_DIR/data/documents" \
    "$APP_DIR/data/logs" \
    "$APP_DIR/data/vision_debug"
}

prepare_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$APP_DIR/.env.example" ]]; then
      cp "$APP_DIR/.env.example" "$ENV_FILE"
      log "Created $ENV_FILE from .env.example"
    else
      : >"$ENV_FILE"
      log "Created empty $ENV_FILE"
    fi
  fi

  replace_or_append_env "$ENV_FILE" "APP_ENV" "prod"
  replace_or_append_env "$ENV_FILE" "APP_HOST" "$APP_HOST"
  replace_or_append_env "$ENV_FILE" "APP_PORT" "$APP_PORT"
  replace_or_append_env "$ENV_FILE" "DEBUG" "false"
  replace_or_append_env "$ENV_FILE" "UPLOAD_DIR" "data/uploads"
  replace_or_append_env "$ENV_FILE" "PARSED_DIR" "data/parsed"
  replace_or_append_env "$ENV_FILE" "DOCUMENT_DB_PATH" "data/documents/documents.db"
  replace_or_append_env "$ENV_FILE" "LOG_DIR" "data/logs"
  replace_or_append_env "$ENV_FILE" "VECTOR_BACKEND" "$VECTOR_BACKEND"
  replace_or_append_env "$ENV_FILE" "EMBEDDING_DEVICE" "cpu"
  replace_or_append_env "$ENV_FILE" "VISION_DEBUG_DIR" "data/vision_debug"
  replace_or_append_env "$ENV_FILE" "RERANK_MODEL_NAME" "BAAI/bge-reranker-base"
  replace_or_append_env "$ENV_FILE" "QUERY_REWRITE_ENABLED" "true"
  replace_or_append_env "$ENV_FILE" "PROMPT_MAX_CONTEXT_CHARS" "6000"

  if [[ "$VECTOR_BACKEND" == "memory" ]]; then
    replace_or_append_env "$ENV_FILE" "VECTOR_BACKEND" "memory"
  else
    replace_or_append_env "$ENV_FILE" "VECTOR_BACKEND" "milvus"
    replace_or_append_env "$ENV_FILE" "MILVUS_URI" "http://127.0.0.1:19530"
  fi

  log "Environment file prepared at $ENV_FILE"
  log "Remember to fill LLM_API_KEY and confirm LLM_MODEL before go-live"
}

deploy_milvus() {
  if [[ "$VECTOR_BACKEND" != "milvus" || "$ENABLE_MILVUS" != "1" ]]; then
    log "Skip Milvus deployment"
    return
  fi

  require_cmd docker
  if ! docker compose version >/dev/null 2>&1; then
    echo "docker compose is required for Milvus deployment" >&2
    exit 1
  fi

  log "Deploying Milvus standalone with Docker Compose"
  sudo mkdir -p "$MILVUS_DIR"
  sudo cp "$APP_DIR/scripts/milvus-standalone.yml" "$MILVUS_DIR/docker-compose.yml"
  sudo docker compose -f "$MILVUS_DIR/docker-compose.yml" up -d
}

install_systemd_service() {
  log "Installing systemd unit at $SYSTEMD_UNIT_PATH"
  sudo tee "$SYSTEMD_UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=${PROJECT_NAME} FastAPI service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python -m uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
}

print_summary() {
  cat <<EOF

Deployment completed.

Service:
  sudo systemctl status ${SERVICE_NAME}
  sudo journalctl -u ${SERVICE_NAME} -f

App URL:
  http://${APP_HOST}:${APP_PORT}

Important follow-up:
  1. Edit ${ENV_FILE} and fill LLM_API_KEY / LLM_MODEL.
  2. If using remote Milvus, update MILVUS_URI.
  3. If you have a local rerank model path, replace RERANK_MODEL_NAME.
EOF
}

main() {
  prepare_app_dir
  install_system_packages
  setup_venv
  prepare_runtime_dirs
  prepare_env
  deploy_milvus
  install_systemd_service
  print_summary
}

main "$@"
