#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-rag-role-play}"
APP_USER="${APP_USER:-ragapp}"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$PROJECT_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
WORKERS="${WORKERS:-1}"
DOMAIN_NAME="${DOMAIN_NAME:-_}"
ENABLE_SYSTEMD="${ENABLE_SYSTEMD:-true}"
ENABLE_NGINX="${ENABLE_NGINX:-true}"
ENABLE_INFRA_DOCKER="${ENABLE_INFRA_DOCKER:-false}"
SKIP_MYSQL_INIT="${SKIP_MYSQL_INIT:-false}"
SKIP_MODEL_PATH_CHECK="${SKIP_MODEL_PATH_CHECK:-false}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-900}"

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-rag_user_cosplay}"
MYSQL_USER="${MYSQL_USER:-rag_app}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-$(openssl rand -hex 16 2>/dev/null || date +%s%N)}"
MYSQL_ADMIN_USER="${MYSQL_ADMIN_USER:-root}"
MYSQL_ADMIN_PASSWORD="${MYSQL_ADMIN_PASSWORD:-${MYSQL_ROOT_PASSWORD:-root}}"

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DB="${REDIS_DB:-0}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"
MILVUS_URI="${MILVUS_URI:-http://127.0.0.1:19530}"
MILVUS_DB_NAME="${MILVUS_DB_NAME:-rag_user_cosplay}"
MILVUS_COLLECTION_NAME="${MILVUS_COLLECTION_NAME:-character_rag}"
EMBEDDING_MODEL_PATH="${EMBEDDING_MODEL_PATH:-/opt/models/BGE-m3}"
RERANKER_MODEL_PATH="${RERANKER_MODEL_PATH:-/opt/models/bge-reranker-base}"
DEVICE="${DEVICE:-cpu}"
USE_FP16="${USE_FP16:-false}"
JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(openssl rand -hex 32 2>/dev/null || date +%s%N)}"

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "请使用 root 用户执行，或通过 sudo 运行此脚本。"
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

install_packages() {
  log "安装系统依赖"
  if command_exists apt-get; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip rsync curl nginx default-mysql-client ca-certificates
  elif command_exists dnf; then
    dnf install -y python3 python3-pip python3-virtualenv rsync curl nginx mysql ca-certificates
  elif command_exists yum; then
    yum install -y python3 python3-pip python3-virtualenv rsync curl nginx mysql ca-certificates
  else
    fail "未识别 apt-get/dnf/yum，请手动安装 python3、venv、pip、rsync、curl、nginx、mysql 客户端。"
  fi
}

ensure_app_user() {
  if ! id "$APP_USER" >/dev/null 2>&1; then
    log "创建运行用户 $APP_USER"
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  fi
}

sync_source() {
  [ -d "$SOURCE_DIR" ] || fail "SOURCE_DIR 不存在: $SOURCE_DIR"
  [ -f "$SOURCE_DIR/requirements.txt" ] || fail "SOURCE_DIR 中未找到 requirements.txt: $SOURCE_DIR"
  [ -f "$SOURCE_DIR/app_run.py" ] || fail "SOURCE_DIR 中未找到 app_run.py: $SOURCE_DIR"
  log "同步项目文件到 $APP_DIR"
  mkdir -p "$APP_DIR"
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    "$SOURCE_DIR/" "$APP_DIR/"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
}

create_venv() {
  log "创建 Python 虚拟环境并安装依赖"
  if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  fi
  "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/.venv"
}

write_env_file() {
  local env_file="$APP_DIR/.env"
  if [ -f "$env_file" ]; then
    log "保留已有环境配置 $env_file"
    return
  fi
  log "生成环境配置 $env_file"
  cat > "$env_file" <<EOF
APP_HOST=$APP_HOST
APP_PORT=$APP_PORT
WORKERS=$WORKERS
EMBEDDING_MODEL_PATH=$EMBEDDING_MODEL_PATH
RERANKER_MODEL_PATH=$RERANKER_MODEL_PATH
MILVUS_URI=$MILVUS_URI
MILVUS_DB_NAME=$MILVUS_DB_NAME
MILVUS_COLLECTION_NAME=$MILVUS_COLLECTION_NAME
MILVUS_TEXT_ANALYZER=chinese
MILVUS_HYBRID_RERANKER=weighted
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT
REDIS_DB=$REDIS_DB
REDIS_PASSWORD=$REDIS_PASSWORD
MYSQL_HOST=$MYSQL_HOST
MYSQL_PORT=$MYSQL_PORT
MYSQL_USER=$MYSQL_USER
MYSQL_PASSWORD=$MYSQL_PASSWORD
MYSQL_DATABASE=$MYSQL_DATABASE
JWT_SECRET_KEY=$JWT_SECRET_KEY
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
SGLANG_BASE_URL=${SGLANG_BASE_URL:-http://127.0.0.1:30000/v1}
SGLANG_MODEL=${SGLANG_MODEL:-qwen-0.8b}
SGLANG_API_KEY=${SGLANG_API_KEY:-EMPTY}
ONLINE_LLM_BASE_URL=${ONLINE_LLM_BASE_URL:-https://api.siliconflow.cn/v1/chat/completions}
ONLINE_LLM_API_KEY=${ONLINE_LLM_API_KEY:-}
ONLINE_LLM_MODEL=${ONLINE_LLM_MODEL:-Pro/deepseek-ai/DeepSeek-V3}
ONLINE_LLM_TIMEOUT=${ONLINE_LLM_TIMEOUT:-120}
MINERU_API_BASE_URL=${MINERU_API_BASE_URL:-https://mineru.net}
MINERU_API_TOKEN=${MINERU_API_TOKEN:-}
MINERU_API_USER_TOKEN=${MINERU_API_USER_TOKEN:-}
MINERU_PDF_MODEL_VERSION=${MINERU_PDF_MODEL_VERSION:-vlm}
MINERU_PDF_LANGUAGE=${MINERU_PDF_LANGUAGE:-auto}
MINERU_PDF_ENABLE_OCR=${MINERU_PDF_ENABLE_OCR:-true}
MINERU_PDF_ENABLE_TABLE=${MINERU_PDF_ENABLE_TABLE:-true}
MINERU_PDF_ENABLE_FORMULA=${MINERU_PDF_ENABLE_FORMULA:-true}
DEVICE=$DEVICE
USE_FP16=$USE_FP16
TOP_K=${TOP_K:-5}
RERANK_TOP_K=${RERANK_TOP_K:-3}
KNOWLEDGE_CHUNK_SIZE=${KNOWLEDGE_CHUNK_SIZE:-400}
KNOWLEDGE_CHUNK_OVERLAP=${KNOWLEDGE_CHUNK_OVERLAP:-80}
EMBEDDING_BATCH_SIZE=${EMBEDDING_BATCH_SIZE:-128}
MILVUS_INSERT_BATCH_SIZE=${MILVUS_INSERT_BATCH_SIZE:-256}
RESPONSE_CACHE_ENABLED=${RESPONSE_CACHE_ENABLED:-true}
STRICT_GROUNDED_ANSWERING=${STRICT_GROUNDED_ANSWERING:-true}
EOF
  chmod 600 "$env_file"
  chown "$APP_USER:$APP_USER" "$env_file"
}

load_env_file() {
  set -a
  . "$APP_DIR/.env"
  set +a
}

validate_runtime_paths() {
  [ -d "$APP_DIR/static" ] || fail "未找到静态前端目录: $APP_DIR/static"
  [ -d "$APP_DIR/data" ] || mkdir -p "$APP_DIR/data"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/data"
  if [ "$SKIP_MODEL_PATH_CHECK" = "true" ]; then
    log "跳过模型目录检查"
    return
  fi
  [ -d "$EMBEDDING_MODEL_PATH" ] || fail "Embedding 模型目录不存在: $EMBEDDING_MODEL_PATH"
  [ -d "$RERANKER_MODEL_PATH" ] || fail "Reranker 模型目录不存在: $RERANKER_MODEL_PATH"
}

validate_mysql_identifiers() {
  [[ "$MYSQL_DATABASE" =~ ^[A-Za-z0-9_]+$ ]] || fail "MYSQL_DATABASE 只能包含字母、数字和下划线: $MYSQL_DATABASE"
  [[ "$MYSQL_USER" =~ ^[A-Za-z0-9_]+$ ]] || fail "MYSQL_USER 只能包含字母、数字和下划线: $MYSQL_USER"
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local name="$3"
  local timeout="${4:-120}"
  local deadline=$((SECONDS + timeout))
  log "等待 $name 端口 $host:$port"
  while [ "$SECONDS" -lt "$deadline" ]; do
    if (echo >/dev/tcp/"$host"/"$port") >/dev/null 2>&1; then
      return
    fi
    sleep 3
  done
  fail "$name 端口等待超时: $host:$port"
}

init_mysql() {
  if [ "$SKIP_MYSQL_INIT" = "true" ]; then
    log "跳过 MySQL 数据库创建"
    return
  fi
  validate_mysql_identifiers
  command_exists mysql || fail "未找到 mysql 客户端"
  wait_for_tcp "$MYSQL_HOST" "$MYSQL_PORT" "MySQL" 180
  local escaped_password
  escaped_password="$(sql_escape "$MYSQL_PASSWORD")"
  log "初始化 MySQL 数据库 $MYSQL_DATABASE"
  MYSQL_PWD="$MYSQL_ADMIN_PASSWORD" mysql --protocol=tcp -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_ADMIN_USER" <<SQL
CREATE DATABASE IF NOT EXISTS \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$MYSQL_USER'@'%' IDENTIFIED BY '$escaped_password';
ALTER USER '$MYSQL_USER'@'%' IDENTIFIED BY '$escaped_password';
GRANT ALL PRIVILEGES ON \`$MYSQL_DATABASE\`.* TO '$MYSQL_USER'@'%';
FLUSH PRIVILEGES;
SQL
}

write_infra_compose() {
  if [ "$ENABLE_INFRA_DOCKER" != "true" ]; then
    return
  fi
  command_exists docker || fail "ENABLE_INFRA_DOCKER=true 需要先安装 Docker"
  docker compose version >/dev/null 2>&1 || fail "ENABLE_INFRA_DOCKER=true 需要 Docker Compose v2"
  log "生成并启动 Docker 基础设施"
  mkdir -p "$APP_DIR/deploy"
  cat > "$APP_DIR/deploy/docker-compose.infra.yml" <<EOF
services:
  mysql:
    image: mysql:8.0
    container_name: ${APP_NAME}-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ADMIN_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE}
      MYSQL_USER: ${MYSQL_USER}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    ports:
      - "${MYSQL_PORT}:3306"
    volumes:
      - mysql_data:/var/lib/mysql
  redis:
    image: redis:7-alpine
    container_name: ${APP_NAME}-redis
    restart: unless-stopped
    ports:
      - "${REDIS_PORT}:6379"
    volumes:
      - redis_data:/data
  etcd:
    image: quay.io/coreos/etcd:v3.5.18
    container_name: ${APP_NAME}-etcd
    restart: unless-stopped
    environment:
      ETCD_AUTO_COMPACTION_MODE: revision
      ETCD_AUTO_COMPACTION_RETENTION: "1000"
      ETCD_QUOTA_BACKEND_BYTES: "4294967296"
      ETCD_SNAPSHOT_COUNT: "50000"
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - etcd_data:/etcd
  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    container_name: ${APP_NAME}-minio
    restart: unless-stopped
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data --console-address ":9001"
    volumes:
      - minio_data:/minio_data
  milvus:
    image: milvusdb/milvus:v2.5.4
    container_name: ${APP_NAME}-milvus
    restart: unless-stopped
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - milvus_data:/var/lib/milvus
    depends_on:
      - etcd
      - minio
volumes:
  mysql_data:
  redis_data:
  etcd_data:
  minio_data:
  milvus_data:
EOF
  docker compose -f "$APP_DIR/deploy/docker-compose.infra.yml" up -d
  sleep 20
}

write_systemd_service() {
  if [ "$ENABLE_SYSTEMD" != "true" ]; then
    return
  fi
  log "写入 systemd 服务"
  cat > "/etc/systemd/system/${APP_NAME}.service" <<EOF
[Unit]
Description=RAG Role Play FastAPI Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host $APP_HOST --port $APP_PORT --workers $WORKERS
Restart=always
RestartSec=5
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$APP_NAME"
  systemctl restart "$APP_NAME"
}

write_nginx_site() {
  if [ "$ENABLE_NGINX" != "true" ]; then
    return
  fi
  log "写入 Nginx 反向代理"
  cat > "/etc/nginx/conf.d/${APP_NAME}.conf" <<EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;
    client_max_body_size 200m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
  nginx -t
  systemctl enable nginx
  systemctl restart nginx
}

wait_for_health() {
  log "等待应用健康检查"
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  local body
  while [ "$SECONDS" -lt "$deadline" ]; do
    body="$(curl -fsS "http://127.0.0.1:${APP_PORT}/health" 2>/dev/null || true)"
    if [ -n "$body" ]; then
      printf '%s\n' "$body" > "/tmp/${APP_NAME}-health.json"
      if printf '%s' "$body" | grep -q '"startup_ready":true'; then
        cat "/tmp/${APP_NAME}-health.json"
        printf '\n'
        return
      fi
      if printf '%s' "$body" | grep -q '"startup_stage":"failed"'; then
        cat "/tmp/${APP_NAME}-health.json"
        printf '\n'
        break
      fi
    fi
    sleep 5
  done
  if [ "$ENABLE_SYSTEMD" = "true" ]; then
    systemctl status "$APP_NAME" --no-pager || true
    journalctl -u "$APP_NAME" -n 120 --no-pager || true
  fi
  fail "健康检查超时，请检查 MySQL、Redis、Milvus、模型路径和日志。"
}

print_result() {
  log "部署完成"
  printf '应用目录: %s\n' "$APP_DIR"
  printf '环境配置: %s/.env\n' "$APP_DIR"
  printf '本机访问: http://127.0.0.1:%s\n' "$APP_PORT"
  if [ "$ENABLE_NGINX" = "true" ]; then
    printf 'Nginx 入口: http://%s/\n' "$DOMAIN_NAME"
  fi
  printf '健康检查: curl http://127.0.0.1:%s/health\n' "$APP_PORT"
  printf '服务日志: journalctl -u %s -f\n' "$APP_NAME"
  printf '重启服务: systemctl restart %s\n' "$APP_NAME"
  printf '查看状态: systemctl status %s --no-pager\n' "$APP_NAME"
}

main() {
  require_root
  install_packages
  ensure_app_user
  sync_source
  create_venv
  write_env_file
  load_env_file
  validate_runtime_paths
  write_infra_compose
  init_mysql
  write_systemd_service
  write_nginx_site
  wait_for_health
  print_result
}

main "$@"
