#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="rag-qa-system"
APP_DIR="${APP_DIR:-/opt/rag-qa-system}"
APP_USER="${APP_USER:-ragqa}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_PORT="${SERVICE_PORT:-8000}"
START_MILVUS="${START_MILVUS:-false}"
INSTALL_SYSTEM_DEPS="${INSTALL_SYSTEM_DEPS:-true}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "请使用 root 用户执行，或使用 sudo 运行：sudo bash scripts/deploy_linux.sh"
    exit 1
  fi
}

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  else
    echo "unknown"
  fi
}

install_system_deps() {
  if [ "$INSTALL_SYSTEM_DEPS" != "true" ]; then
    log "跳过系统依赖安装"
    return
  fi

  local manager
  manager="$(detect_pkg_manager)"
  log "安装系统依赖，包管理器：$manager"

  case "$manager" in
    apt)
      apt-get update
      apt-get install -y python3 python3-venv python3-pip curl ca-certificates build-essential rsync
      ;;
    dnf)
      dnf install -y python3 python3-pip curl ca-certificates gcc gcc-c++ make rsync
      ;;
    yum)
      yum install -y python3 python3-pip curl ca-certificates gcc gcc-c++ make rsync
      ;;
    *)
      echo "未识别包管理器，请先手动安装 Python 3.11+、python3-venv、pip、curl、gcc。"
      ;;
  esac
}

ensure_user() {
  if ! id "$APP_USER" >/dev/null 2>&1; then
    log "创建运行用户：$APP_USER"
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  fi
}

run_as_app_user() {
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$APP_USER" -- "$@"
  else
    su -s /bin/sh "$APP_USER" -c "$(printf '%q ' "$@")"
  fi
}

prepare_app_dir() {
  log "准备部署目录：$APP_DIR"
  mkdir -p "$APP_DIR"
  rsync -a \
    --exclude ".git" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".venv" \
    "$PROJECT_ROOT"/ "$APP_DIR"/

  mkdir -p "$APP_DIR/data/uploads" "$APP_DIR/data/parsed" "$APP_DIR/data/documents" "$APP_DIR/data/logs"

  if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    sed -i 's/^APP_ENV=.*/APP_ENV=prod/' "$APP_DIR/.env"
    sed -i 's/^DEBUG=.*/DEBUG=false/' "$APP_DIR/.env"
    sed -i "s/^APP_PORT=.*/APP_PORT=$SERVICE_PORT/" "$APP_DIR/.env"
    sed -i 's/^EMBEDDING_DEVICE=.*/EMBEDDING_DEVICE=cpu/' "$APP_DIR/.env"
    log "已生成 $APP_DIR/.env，请部署后填写 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 等配置"
  fi

  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
}

install_python_deps() {
  log "创建虚拟环境并安装 Python 依赖"
  run_as_app_user "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  run_as_app_user "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  run_as_app_user "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
}

install_service() {
  log "写入 systemd 服务"
  cat >/etc/systemd/system/${APP_NAME}.service <<EOF
[Unit]
Description=RAG QA System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run.py
Restart=always
RestartSec=5
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$APP_NAME"
  systemctl restart "$APP_NAME"
}

start_milvus_if_needed() {
  if [ "$START_MILVUS" != "true" ]; then
    log "跳过 Milvus 启动。若使用外部 Milvus，请在 .env 中配置 MILVUS_URI"
    return
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "START_MILVUS=true 需要 Docker，请先安装 Docker。"
    exit 1
  fi

  log "使用 Docker 启动 Milvus Standalone"
  docker rm -f milvus-standalone >/dev/null 2>&1 || true
  docker run -d \
    --name milvus-standalone \
    --security-opt seccomp:unconfined \
    -p 19530:19530 \
    -p 9091:9091 \
    -v milvus_data:/var/lib/milvus \
    milvusdb/milvus:v2.5.0 \
    milvus run standalone
}

health_check() {
  log "等待服务启动并检查健康状态"
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${SERVICE_PORT}/api/health" >/dev/null 2>&1; then
      log "部署完成：访问 http://服务器IP:${SERVICE_PORT}"
      return
    fi
    sleep 2
  done

  echo "服务未通过健康检查，请查看日志：journalctl -u ${APP_NAME} -f"
  exit 1
}

main() {
  need_root
  install_system_deps
  ensure_user
  start_milvus_if_needed
  prepare_app_dir
  install_python_deps
  install_service
  health_check
}

main "$@"
