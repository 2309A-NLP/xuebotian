#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR=".venv"
HOST="0.0.0.0"
PORT="8000"
BOOTSTRAP_ENV="false"
DEBUG="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --venv-dir)
      VENV_DIR="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --bootstrap-env)
      BOOTSTRAP_ENV="true"
      shift
      ;;
    --debug)
      DEBUG="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo "Python 3.11+ was not found on PATH." >&2
  exit 1
}

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$BOOTSTRAP_ENV" == "true" && -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "Created .env from .env.example. Fill in secrets and external service settings, then rerun."
    exit 1
  fi
  echo "Missing .env. Copy .env.example and complete the configuration, or rerun with --bootstrap-env." >&2
  exit 1
fi

for dir in \
  data/logs \
  data/uploads \
  data/parsed \
  data/images \
  data/mineru_debug \
  data/vision_debug \
  data/documents; do
  mkdir -p "$PROJECT_ROOT/$dir"
done

PYTHON_BIN="$(resolve_python)"
VENV_PATH="$PROJECT_ROOT/$VENV_DIR"
VENV_PYTHON="$VENV_PATH/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Creating virtual environment: $VENV_PATH"
  "$PYTHON_BIN" -m venv "$VENV_PATH"
fi

echo "Installing dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"

export HOST="$HOST"
export APP_HOST="$HOST"
export PORT="$PORT"
export APP_PORT="$PORT"
export DEBUG="$DEBUG"
if [[ "$DEBUG" == "true" ]]; then
  export ENVIRONMENT="development"
else
  export ENVIRONMENT="production"
fi

echo "Starting service: http://$HOST:$PORT"
exec "$VENV_PYTHON" "$PROJECT_ROOT/run.py"
