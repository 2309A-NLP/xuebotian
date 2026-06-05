#!/usr/bin/env bash
set -Eeuo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST_NAME="${HOST_NAME:-0.0.0.0}"
PORT="${PORT:-8000}"
VECTOR_BACKEND="${VECTOR_BACKEND:-milvus}"
EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-}"
SKIP_INSTALL=0
NO_START=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy.sh [options]

Options:
  --python <bin>          Python command, default: python3
  --host <host>           App listen host, default: 0.0.0.0
  --port <port>           App listen port, default: 8000
  --vector <backend>      Vector backend: milvus or memory, default: milvus
  --cpu                   Force EMBEDDING_DEVICE=cpu
  --skip-install          Skip pip dependency installation
  --no-start              Prepare environment only, do not start app
  -h, --help              Show this help

Examples:
  bash scripts/deploy.sh
  bash scripts/deploy.sh --vector memory --cpu
  bash scripts/deploy.sh --host 0.0.0.0 --port 8000 --no-start
EOF
}

log_step() {
  printf '\n==> %s\n' "$1"
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

set_or_append_env() {
  local file="$1"
  local key="$2"
  local value="$3"

  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

check_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      [[ $# -ge 2 ]] || die "--python requires a value"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --host)
      [[ $# -ge 2 ]] || die "--host requires a value"
      HOST_NAME="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || die "--port requires a value"
      PORT="$2"
      shift 2
      ;;
    --vector)
      [[ $# -ge 2 ]] || die "--vector requires a value"
      VECTOR_BACKEND="$2"
      shift 2
      ;;
    --cpu)
      EMBEDDING_DEVICE="cpu"
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --no-start)
      NO_START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

if [[ "$VECTOR_BACKEND" != "milvus" && "$VECTOR_BACKEND" != "memory" ]]; then
  die "--vector must be either milvus or memory"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

log_step "Checking system dependencies"
check_command "$PYTHON_BIN" || die "Python command not found: ${PYTHON_BIN}"
"$PYTHON_BIN" --version

if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
  cat >&2 <<EOF
Python venv module is unavailable.
On Ubuntu/Debian, install it with:
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip
EOF
  exit 1
fi

log_step "Creating virtual environment"
if [[ ! -d ".venv" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
[[ -x "$VENV_PYTHON" ]] || die "Virtual environment Python was not found: ${VENV_PYTHON}"

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  log_step "Installing Python dependencies"
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install -r requirements.txt
else
  log_step "Skipping dependency installation"
fi

log_step "Preparing .env"
if [[ ! -f ".env" ]]; then
  if [[ -f ".env.example" ]]; then
    cp .env.example .env
  else
    touch .env
  fi
fi

set_or_append_env ".env" "APP_HOST" "$HOST_NAME"
set_or_append_env ".env" "APP_PORT" "$PORT"
set_or_append_env ".env" "VECTOR_BACKEND" "$VECTOR_BACKEND"

if [[ -n "$EMBEDDING_DEVICE" ]]; then
  set_or_append_env ".env" "EMBEDDING_DEVICE" "$EMBEDDING_DEVICE"
fi

log_step "Creating runtime directories"
mkdir -p data/uploads data/parsed data/documents data/logs

if [[ "$VECTOR_BACKEND" == "milvus" ]]; then
  log_step "Checking Milvus port"
  if check_command nc; then
    if ! nc -z 127.0.0.1 19530 >/dev/null 2>&1; then
      printf 'Milvus does not appear to be listening on 127.0.0.1:19530.\n' >&2
      printf 'Start Milvus first, or run with --vector memory for local demonstration.\n' >&2
    fi
  else
    printf 'nc is not installed, skipping Milvus port check.\n' >&2
  fi
fi

log_step "Deployment summary"
cat <<EOF
Project root: ${PROJECT_ROOT}
Virtual env : ${VENV_PYTHON}
Host        : ${HOST_NAME}
Port        : ${PORT}
Vector DB   : ${VECTOR_BACKEND}
URL         : http://127.0.0.1:${PORT}
EOF

if [[ "$NO_START" -eq 1 ]]; then
  cat <<EOF

Environment is ready. Start later with:
  ./.venv/bin/python run.py
EOF
  exit 0
fi

log_step "Starting application"
exec "$VENV_PYTHON" run.py
