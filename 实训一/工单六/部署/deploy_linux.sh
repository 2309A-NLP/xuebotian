#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="${APP_NAME:-raggd}"
APP_USER="${APP_USER:-$(whoami)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
SERVICE_NAME="${SERVICE_NAME:-raggd}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"

INSTALL_SYSTEM_PACKAGES="${INSTALL_SYSTEM_PACKAGES:-1}"
INSTALL_LOCAL_REDIS="${INSTALL_LOCAL_REDIS:-1}"
INSTALL_LOCAL_MARIADB="${INSTALL_LOCAL_MARIADB:-1}"
ENABLE_SYSTEMD_SERVICE="${ENABLE_SYSTEMD_SERVICE:-1}"
DEFAULT_VECTOR_BACKEND="${DEFAULT_VECTOR_BACKEND:-memory}"

ENV_FILE="$PROJECT_DIR/.env"
DB_NAME="${DB_NAME:-raggd}"
DB_USER="${DB_USER:-raggd}"
DB_PASSWORD="${DB_PASSWORD:-}"
AUTH_SECRET_KEY="${AUTH_SECRET_KEY:-}"

log() {
  printf '[deploy] %s\n' "$1"
}

fail() {
  printf '[deploy][error] %s\n' "$1" >&2
  exit 1
}

run_as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令: $1"
}

random_string() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24
}

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    echo "dnf"
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    echo "yum"
    return
  fi
  echo ""
}

install_system_packages() {
  [[ "$INSTALL_SYSTEM_PACKAGES" == "1" ]] || return 0

  local pm
  pm="$(detect_pkg_manager)"
  if [[ -z "$pm" ]]; then
    log "未识别包管理器，跳过系统包安装"
    return 0
  fi

  log "安装系统依赖"
  case "$pm" in
    apt)
      run_as_root apt-get update
      run_as_root apt-get install -y \
        python3 python3-venv python3-pip build-essential pkg-config \
        libffi-dev libssl-dev curl git redis-server mariadb-server
      ;;
    dnf)
      run_as_root dnf install -y \
        python3 python3-pip python3-virtualenv gcc gcc-c++ make pkgconfig \
        libffi-devel openssl-devel curl git redis mariadb-server
      ;;
    yum)
      run_as_root yum install -y \
        python3 python3-pip gcc gcc-c++ make pkgconfig \
        libffi-devel openssl-devel curl git redis mariadb-server
      ;;
  esac
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$PROJECT_DIR/.env.example" ]]; then
      cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
      log "已从 .env.example 生成 .env"
    else
      touch "$ENV_FILE"
      log "已创建空的 .env"
    fi
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}

ensure_runtime_dirs() {
  mkdir -p \
    "$PROJECT_DIR/data/uploads" \
    "$PROJECT_DIR/data/parsed" \
    "$PROJECT_DIR/data/images" \
    "$PROJECT_DIR/data/mineru_debug" \
    "$PROJECT_DIR/data/vision_debug" \
    "$PROJECT_DIR/data/logs" \
    "$PROJECT_DIR/data/documents"
}

prepare_local_services() {
  if [[ "$INSTALL_LOCAL_REDIS" == "1" ]]; then
    log "启动 Redis"
    if command -v systemctl >/dev/null 2>&1; then
      run_as_root systemctl enable --now redis-server || run_as_root systemctl enable --now redis
    fi
    set_env_value "REDIS_URL" "redis://127.0.0.1:6379/0"
  fi

  if [[ "$INSTALL_LOCAL_MARIADB" == "1" ]]; then
    log "启动 MariaDB"
    if command -v systemctl >/dev/null 2>&1; then
      run_as_root systemctl enable --now mariadb || run_as_root systemctl enable --now mysql
    fi

    if [[ -z "$DB_PASSWORD" ]]; then
      DB_PASSWORD="$(random_string)"
    fi
    if [[ -z "$AUTH_SECRET_KEY" ]]; then
      AUTH_SECRET_KEY="$(random_string)$(random_string)"
    fi

    log "创建本地数据库与应用账号"
    run_as_root mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

    set_env_value "MYSQL_HOST" "127.0.0.1"
    set_env_value "MYSQL_PORT" "3306"
    set_env_value "MYSQL_USER" "$DB_USER"
    set_env_value "MYSQL_PASSWORD" "$DB_PASSWORD"
    set_env_value "MYSQL_DATABASE" "$DB_NAME"
    set_env_value "AUTH_SECRET_KEY" "$AUTH_SECRET_KEY"
  fi
}

prepare_app_env() {
  log "写入基础运行配置"
  set_env_value "APP_HOST" "$APP_HOST"
  set_env_value "APP_PORT" "$APP_PORT"
  set_env_value "DEBUG" "false"
  set_env_value "VECTOR_BACKEND" "$DEFAULT_VECTOR_BACKEND"
  set_env_value "UPLOAD_DIR" "data/uploads"
  set_env_value "PARSED_DIR" "data/parsed"
  set_env_value "DOCUMENT_DB_PATH" "data/documents/documents.db"
  set_env_value "LOG_DIR" "data/logs"
}

setup_venv() {
  require_cmd "$PYTHON_BIN"
  log "创建虚拟环境: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"

  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r "$PROJECT_DIR/requirements.txt"
  python -m pip install redis
}

install_systemd_service() {
  [[ "$ENABLE_SYSTEMD_SERVICE" == "1" ]] || return 0
  command -v systemctl >/dev/null 2>&1 || {
    log "systemctl 不可用，跳过 systemd 服务创建"
    return 0
  }

  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
  log "写入 systemd 服务: $service_file"
  run_as_root tee "$service_file" >/dev/null <<EOF
[Unit]
Description=${APP_NAME} FastAPI service
After=network.target redis-server.service mariadb.service mysql.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${PROJECT_DIR}/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  run_as_root systemctl daemon-reload
  run_as_root systemctl enable --now "$SERVICE_NAME"
}

print_summary() {
  cat <<EOF

部署完成。

项目目录: ${PROJECT_DIR}
虚拟环境: ${VENV_DIR}
环境文件: ${ENV_FILE}
访问地址: http://${APP_HOST}:${APP_PORT}

当前脚本默认把 VECTOR_BACKEND 设置为 ${DEFAULT_VECTOR_BACKEND}。
如需启用生产向量检索，请在 .env 中改回 milvus 并补齐 MILVUS_* 配置。

仍需你确认的配置:
1. LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
2. 如使用 MinerU，补齐 MINERU_* 配置
3. 如需 HTTPS，请额外接入 Nginx 或其他反向代理

常用命令:
  查看服务状态: sudo systemctl status ${SERVICE_NAME}
  查看服务日志: sudo journalctl -u ${SERVICE_NAME} -f
  手动启动项目: source ${VENV_DIR}/bin/activate && python ${PROJECT_DIR}/run.py

EOF
}

main() {
  install_system_packages
  ensure_env_file
  ensure_runtime_dirs
  prepare_local_services
  prepare_app_env
  setup_venv
  install_systemd_service
  print_summary
}

main "$@"
