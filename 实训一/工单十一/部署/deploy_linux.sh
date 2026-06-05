#!/usr/bin/env bash
set -euo pipefail

# Linux deployment script for the RAG work-order embedding fine-tuning project.
# Usage:
#   bash deploy_linux.sh
# Optional environment variables:
#   PROJECT_DIR=/root/autodl-tmp/project
#   MODEL_DIR=/root/autodl-tmp/model/bge-base-zh-v1.5
#   VENV_DIR=/root/autodl-tmp/envs/rag_gd11
#   CUDA_INDEX_URL=https://download.pytorch.org/whl/cu118
#   RUN_PIPELINE=1

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
MODEL_DIR="${MODEL_DIR:-/root/autodl-tmp/model/bge-base-zh-v1.5}"
VENV_DIR="${VENV_DIR:-/root/autodl-tmp/envs/rag_gd11}"
CUDA_INDEX_URL="${CUDA_INDEX_URL:-https://download.pytorch.org/whl/cu118}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
RUN_PIPELINE="${RUN_PIPELINE:-0}"

echo "[1/8] Project directory: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

echo "[2/8] Installing system dependencies"
if command -v apt-get >/dev/null 2>&1; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-sim git curl python3 python3-venv python3-pip
  else
    sudo apt-get update
    sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-sim git curl python3 python3-venv python3-pip
  fi
else
  echo "apt-get not found. Please install poppler-utils, tesseract-ocr, git, curl, python3, python3-venv and pip manually."
fi

echo "[3/8] Creating Python virtual environment: ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel

echo "[4/8] Installing PyTorch"
pip install torch torchvision torchaudio --index-url "${CUDA_INDEX_URL}"

echo "[5/8] Installing project Python dependencies"
pip install \
  datasets \
  sentence-transformers \
  openai \
  pandas \
  nltk \
  "unstructured[all-docs]" \
  pi_heif \
  "huggingface_hub[cli]"

echo "[6/8] Downloading NLTK resources"
python - <<'PY'
import nltk
for name in ["punkt", "punkt_tab", "averaged_perceptron_tagger"]:
    nltk.download(name)
PY

echo "[7/8] Preparing base embedding model"
mkdir -p "$(dirname "${MODEL_DIR}")"
if [ ! -f "${MODEL_DIR}/config.json" ]; then
  export HF_ENDPOINT
  hf download BAAI/bge-base-zh-v1.5 --local-dir "${MODEL_DIR}"
else
  echo "Model already exists at ${MODEL_DIR}"
fi

echo "[8/8] Environment summary"
python - <<'PY'
import torch
print("Python environment ready")
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("CUDA device:", torch.cuda.get_device_name(0))
PY

cat <<EOF

Deployment finished.

Before running data generation, set your API key:
  export SILICONFLOW_API_KEY="your_api_key"

Expected run order:
  python "PDF解析和文本处理.py"
  python "训练与评估.py"

Current settings:
  PROJECT_DIR=${PROJECT_DIR}
  MODEL_DIR=${MODEL_DIR}
  VENV_DIR=${VENV_DIR}

EOF

if [ "${RUN_PIPELINE}" = "1" ]; then
  if [ -z "${SILICONFLOW_API_KEY:-}" ]; then
    echo "RUN_PIPELINE=1 was set, but SILICONFLOW_API_KEY is empty. Stop before API call."
    exit 1
  fi
  python "PDF解析和文本处理.py"
  python "训练与评估.py"
fi
