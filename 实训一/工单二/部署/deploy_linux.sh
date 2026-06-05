#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-rag-qa-system}"
APP_USER="${APP_USER:-ragapp}"
APP_DIR="${APP_DIR:-/opt/rag-qa-system}"
APP_PORT="${APP_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
SERVICE_NAME="${SERVICE_NAME:-rag-qa-system}"
INSTALL_MILVUS="${INSTALL_MILVUS:-false}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Please run as root: sudo bash scripts/deploy_linux.sh"
    exit 1
  fi
}

install_system_packages() {
  log "Installing system packages"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y \
      curl git rsync build-essential pkg-config \
      python3 python3-venv python3-pip \
      libgl1 libglib2.0-0
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y \
      curl git rsync gcc gcc-c++ make pkgconfig \
      python3 python3-pip \
      mesa-libGL glib2
  elif command -v yum >/dev/null 2>&1; then
    yum install -y \
      curl git rsync gcc gcc-c++ make pkgconfig \
      python3 python3-pip \
      mesa-libGL glib2
  else
    echo "Unsupported Linux distribution. Please install Python 3.11+, venv, pip, git, rsync and build tools manually."
    exit 1
  fi
}

ensure_python() {
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  fi

  "${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required")
PY
}

create_app_user() {
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    log "Creating application user: ${APP_USER}"
    useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
  fi
}

sync_project() {
  log "Syncing project to ${APP_DIR}"
  mkdir -p "${APP_DIR}"
  rsync -a --delete \
    --exclude ".git" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".venv" \
    "${REPO_DIR}/" "${APP_DIR}/"

  mkdir -p \
    "${APP_DIR}/data/uploads" \
    "${APP_DIR}/data/parsed" \
    "${APP_DIR}/data/documents" \
    "${APP_DIR}/data/logs"

  if [[ ! -f "${APP_DIR}/.env" && -f "${APP_DIR}/.env.example" ]]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  fi

  sed -i "s/^APP_ENV=.*/APP_ENV=prod/" "${APP_DIR}/.env" || true
  sed -i "s/^DEBUG=.*/DEBUG=false/" "${APP_DIR}/.env" || true
  sed -i "s/^APP_HOST=.*/APP_HOST=0.0.0.0/" "${APP_DIR}/.env" || true
  sed -i "s/^APP_PORT=.*/APP_PORT=${APP_PORT}/" "${APP_DIR}/.env" || true

  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
}

install_python_deps() {
  log "Creating virtualenv and installing Python dependencies"
  sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
  sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip wheel setuptools
  sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
}

install_optional_milvus() {
  if [[ "${INSTALL_MILVUS}" != "true" ]]; then
    return
  fi

  log "Installing standalone Milvus with Docker Compose"
  if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
  fi

  mkdir -p "${APP_DIR}/deploy/milvus"
  cat > "${APP_DIR}/deploy/milvus/docker-compose.yml" <<'YAML'
services:
  etcd:
    image: quay.io/coreos/etcd:v3.5.18
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - ./volumes/etcd:/etcd
  minio:
    image: minio/minio:RELEASE.2024-05-28T17-19-04Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data
    volumes:
      - ./volumes/minio:/minio_data
  standalone:
    image: milvusdb/milvus:v2.4.8
    command: ["milvus", "run", "standalone"]
    security_opt:
      - seccomp:unconfined
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - ./volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"
      - "9091:9091"
    depends_on:
      - etcd
      - minio
YAML

  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/deploy/milvus"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${APP_DIR}/deploy/milvus/docker-compose.yml" up -d
  else
    docker-compose -f "${APP_DIR}/deploy/milvus/docker-compose.yml" up -d
  fi
}

write_systemd_service() {
  log "Writing systemd service: ${SERVICE_NAME}"
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=${APP_NAME}
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run.py
Restart=always
RestartSec=5
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}"
}

health_check() {
  log "Checking service health"
  sleep 3
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
  curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" || {
    echo
    echo "Health check failed. Check logs with:"
    echo "  journalctl -u ${SERVICE_NAME} -f"
    exit 1
  }
  echo
  log "Deployment completed: http://SERVER_IP:${APP_PORT}"
}

main() {
  need_root
  install_system_packages
  ensure_python
  create_app_user
  sync_project
  install_python_deps
  install_optional_milvus
  write_systemd_service
  health_check
}

main "$@"
