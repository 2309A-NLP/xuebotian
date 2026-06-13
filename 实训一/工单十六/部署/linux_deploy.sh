#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

usage() {
  cat <<'EOF'
Usage:
  bash qwen3-VL-2B/linux_deploy.sh [prepare|train|merge|eval|api|all]

Actions:
  prepare  Generate Linux runtime dataset and YAML configs.
  train    Run LoRA SFT training.
  merge    Merge LoRA adapter into a standalone model.
  eval     Evaluate baseline model and merged model.
  api      Start LLaMA-Factory OpenAI-style API with merged model.
  all      Run prepare -> train -> merge -> eval.

Important environment variables:
  PYTHON_BIN           Python executable. Default: python3
  REPO_DIR             LLaMA-Factory root. Default: parent of script dir
  MODEL_PATH           Base model path on Linux. Default: /data/models/Qwen3-VL-2B-Instruct
  IMAGE_ROOT           Linux path mapped to the original Windows images root.
                       Default: /data/patent_images
  SOURCE_TRAIN_JSON    Source Windows dataset json.
  SOURCE_EVAL_JSONL    Source Windows eval jsonl.
  ADAPTER_DIR          LoRA output dir. Default: ${REPO_DIR}/saves/qwen3-vl-2b-patent-lora
  MERGED_DIR           Merged model dir. Default: ${REPO_DIR}/saves/merge_model
  CUDA_VISIBLE_DEVICES GPU ids. Default: 0
  INSTALL_DEPS         Set to 1 to run pip install steps during prepare.
  API_HOST             API host for `api` action. Default: 0.0.0.0
  API_PORT             API port for `api` action. Default: 8000

Examples:
  export MODEL_PATH=/data/models/Qwen3-VL-2B-Instruct
  export IMAGE_ROOT=/data/rag_images/images
  bash qwen3-VL-2B/linux_deploy.sh prepare

  export CUDA_VISIBLE_DEVICES=0,1
  bash qwen3-VL-2B/linux_deploy.sh all

  export API_PORT=9000
  bash qwen3-VL-2B/linux_deploy.sh api
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
WORK_DIR="${WORK_DIR:-${SCRIPT_DIR}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

DATA_DIR="${DATA_DIR:-${REPO_DIR}/data}"
SOURCE_TRAIN_JSON="${SOURCE_TRAIN_JSON:-${DATA_DIR}/patent_multimodal_sharegpt_windows.json}"
SOURCE_EVAL_JSONL="${SOURCE_EVAL_JSONL:-${DATA_DIR}/pinggu.jsonl}"
IMAGE_ROOT="${IMAGE_ROOT:-/data/patent_images}"
WINDOWS_PREFIX="${WINDOWS_PREFIX:-}"
LINUX_PREFIX="${LINUX_PREFIX:-}"

RUNTIME_DIR="${RUNTIME_DIR:-${WORK_DIR}/linux_runtime}"
RUNTIME_DATA_DIR="${RUNTIME_DATA_DIR:-${RUNTIME_DIR}/data}"
TRAIN_DATASET_NAME="${TRAIN_DATASET_NAME:-patent_multimodal_linux}"
TRAIN_DATASET_FILE="${TRAIN_DATASET_FILE:-patent_multimodal_sharegpt_linux.json}"
EVAL_DATASET_FILE="${EVAL_DATASET_FILE:-pinggu_linux.jsonl}"

MODEL_PATH="${MODEL_PATH:-/data/models/Qwen3-VL-2B-Instruct}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${REPO_DIR}/saves}"
ADAPTER_DIR="${ADAPTER_DIR:-${OUTPUT_ROOT}/qwen3-vl-2b-patent-lora}"
MERGED_DIR="${MERGED_DIR:-${OUTPUT_ROOT}/merge_model}"

TRAIN_YAML="${TRAIN_YAML:-${WORK_DIR}/train_qwen3_vl_2b_lora_linux.yaml}"
MERGE_YAML="${MERGE_YAML:-${WORK_DIR}/merge_lora_model_linux.yaml}"
INFER_YAML="${INFER_YAML:-${WORK_DIR}/infer_qwen3_vl_2b_linux.yaml}"

EVAL_BASELINE_DIR="${EVAL_BASELINE_DIR:-${WORK_DIR}/linux_eval_before}"
EVAL_FINETUNED_DIR="${EVAL_FINETUNED_DIR:-${WORK_DIR}/linux_eval_after}"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

CUTOFF_LEN="${CUTOFF_LEN:-4096}"
MAX_SAMPLES="${MAX_SAMPLES:-1000}"
PREPROCESSING_WORKERS="${PREPROCESSING_WORKERS:-4}"
DATALOADER_WORKERS="${DATALOADER_WORKERS:-4}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
LEARNING_RATE="${LEARNING_RATE:-2.0e-4}"
NUM_TRAIN_EPOCHS="${NUM_TRAIN_EPOCHS:-20.0}"
WARMUP_STEPS="${WARMUP_STEPS:-100}"
SAVE_STEPS="${SAVE_STEPS:-100}"
LOGGING_STEPS="${LOGGING_STEPS:-10}"
EVAL_STEPS="${EVAL_STEPS:-100}"
VAL_SIZE="${VAL_SIZE:-0.1}"

action="${1:-all}"
PREPARE_DONE=0

check_paths() {
  [[ -f "${SOURCE_TRAIN_JSON}" ]] || die "source train dataset not found: ${SOURCE_TRAIN_JSON}"
  [[ -f "${SOURCE_EVAL_JSONL}" ]] || die "source eval dataset not found: ${SOURCE_EVAL_JSONL}"
  [[ -f "${WORK_DIR}/evaluate_model.py" ]] || die "evaluate_model.py not found in ${WORK_DIR}"
}

prepare_dirs() {
  mkdir -p \
    "${RUNTIME_DATA_DIR}" \
    "${EVAL_BASELINE_DIR}" \
    "${EVAL_FINETUNED_DIR}" \
    "$(dirname -- "${ADAPTER_DIR}")" \
    "$(dirname -- "${MERGED_DIR}")"
}

require_adapter_ready() {
  if [[ -f "${ADAPTER_DIR}/adapter_config.json" ]]; then
    return 0
  fi

  compgen -G "${ADAPTER_DIR}/adapter_model*" >/dev/null || die "adapter artifacts not found in ${ADAPTER_DIR}"
}

require_merged_ready() {
  [[ -f "${MERGED_DIR}/config.json" ]] || die "merged model not ready: ${MERGED_DIR}/config.json not found"
}

install_deps() {
  log "Installing Python dependencies"
  "${PYTHON_BIN}" -m pip install -U pip
  "${PYTHON_BIN}" -m pip install -e "${REPO_DIR}"
  "${PYTHON_BIN}" -m pip install rouge-score nltk
}

remap_datasets() {
  log "Generating Linux runtime dataset files"
  export SOURCE_TRAIN_JSON SOURCE_EVAL_JSONL RUNTIME_DATA_DIR TRAIN_DATASET_NAME TRAIN_DATASET_FILE EVAL_DATASET_FILE IMAGE_ROOT WINDOWS_PREFIX LINUX_PREFIX
  "${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

source_train = Path(os.environ["SOURCE_TRAIN_JSON"])
source_eval = Path(os.environ["SOURCE_EVAL_JSONL"])
runtime_data_dir = Path(os.environ["RUNTIME_DATA_DIR"])
train_dataset_name = os.environ["TRAIN_DATASET_NAME"]
train_dataset_file = os.environ["TRAIN_DATASET_FILE"]
eval_dataset_file = os.environ["EVAL_DATASET_FILE"]
image_root = os.environ["IMAGE_ROOT"].rstrip("/\\")
windows_prefix = os.environ.get("WINDOWS_PREFIX", "").replace("\\", "/").rstrip("/")
linux_prefix = os.environ.get("LINUX_PREFIX", "").rstrip("/")

runtime_data_dir.mkdir(parents=True, exist_ok=True)

def normalize_path(path: str) -> str:
    if not isinstance(path, str):
        return path

    norm = path.replace("\\\\", "/").replace("\\", "/")

    if windows_prefix and linux_prefix and norm.startswith(windows_prefix):
        suffix = norm[len(windows_prefix):].lstrip("/")
        return f"{linux_prefix}/{suffix}" if suffix else linux_prefix

    marker = "/images/"
    if marker in norm:
        suffix = norm.split(marker, 1)[1].lstrip("/")
        return f"{image_root}/{suffix}" if suffix else image_root

    return norm

def patch_images(obj):
    if isinstance(obj, dict):
        if "images" in obj and isinstance(obj["images"], list):
            obj["images"] = [normalize_path(p) for p in obj["images"]]
        if "image" in obj and isinstance(obj["image"], str):
            obj["image"] = normalize_path(obj["image"])
    return obj

train_data = json.loads(source_train.read_text(encoding="utf-8"))
for item in train_data:
    patch_images(item)

(runtime_data_dir / train_dataset_file).write_text(
    json.dumps(train_data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

with source_eval.open("r", encoding="utf-8") as reader, (runtime_data_dir / eval_dataset_file).open("w", encoding="utf-8") as writer:
    for line in reader:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        patch_images(row)
        writer.write(json.dumps(row, ensure_ascii=False) + "\n")

dataset_info = {
    train_dataset_name: {
        "file_name": train_dataset_file,
        "formatting": "sharegpt",
        "columns": {
            "messages": "conversations",
            "images": "images",
        },
        "tags": {
            "role_tag": "from",
            "content_tag": "value",
            "user_tag": "human",
            "assistant_tag": "gpt",
            "system_tag": "system",
        },
    }
}

(runtime_data_dir / "dataset_info.json").write_text(
    json.dumps(dataset_info, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
PY
}

render_train_yaml() {
  cat > "${TRAIN_YAML}" <<EOF
### model
model_name_or_path: ${MODEL_PATH}
template: qwen3_vl_nothink
trust_remote_code: true

### method
stage: sft
do_train: true
finetuning_type: lora
lora_target: all
lora_rank: 32
lora_alpha: 64
lora_dropout: 0.05
use_rslora: true

### dataset
dataset_dir: ${RUNTIME_DATA_DIR}
dataset: ${TRAIN_DATASET_NAME}
cutoff_len: ${CUTOFF_LEN}
max_samples: ${MAX_SAMPLES}
overwrite_cache: true
preprocessing_num_workers: ${PREPROCESSING_WORKERS}
dataloader_num_workers: ${DATALOADER_WORKERS}

### output
output_dir: ${ADAPTER_DIR}
logging_steps: ${LOGGING_STEPS}
save_steps: ${SAVE_STEPS}
plot_loss: true
overwrite_output_dir: true
report_to: none

### train
per_device_train_batch_size: ${PER_DEVICE_TRAIN_BATCH_SIZE}
gradient_accumulation_steps: ${GRADIENT_ACCUMULATION_STEPS}
learning_rate: ${LEARNING_RATE}
num_train_epochs: ${NUM_TRAIN_EPOCHS}
lr_scheduler_type: cosine
warmup_steps: ${WARMUP_STEPS}
bf16: true
ddp_timeout: 180000000

### eval
val_size: ${VAL_SIZE}
per_device_eval_batch_size: 1
eval_strategy: steps
eval_steps: ${EVAL_STEPS}
EOF
}

render_merge_yaml() {
  cat > "${MERGE_YAML}" <<EOF
### model
model_name_or_path: ${MODEL_PATH}
adapter_name_or_path: ${ADAPTER_DIR}
template: qwen3_vl_nothink
trust_remote_code: true
finetuning_type: lora

### export
export_dir: ${MERGED_DIR}
export_size: 2
export_device: cpu
export_legacy_format: false
EOF
}

render_infer_yaml() {
  cat > "${INFER_YAML}" <<EOF
model_name_or_path: ${MERGED_DIR}
template: qwen3_vl_nothink
infer_backend: huggingface
trust_remote_code: true
EOF
}

render_configs() {
  log "Rendering Linux YAML configs"
  render_train_yaml
  render_merge_yaml
  render_infer_yaml
}

prepare_action() {
  if [[ "${PREPARE_DONE}" == "1" ]]; then
    return 0
  fi

  require_cmd "${PYTHON_BIN}"
  check_paths
  prepare_dirs

  if [[ "${INSTALL_DEPS:-0}" == "1" ]]; then
    install_deps
  else
    log "Skipping dependency installation. Set INSTALL_DEPS=1 to enable it."
  fi

  remap_datasets
  render_configs

  log "Prepare completed"
  log "Runtime dataset dir: ${RUNTIME_DATA_DIR}"
  log "Train config: ${TRAIN_YAML}"
  log "Merge config: ${MERGE_YAML}"
  log "Infer config: ${INFER_YAML}"
  PREPARE_DONE=1
}

train_action() {
  require_cmd llamafactory-cli
  prepare_action
  log "Starting training with CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}"
  CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" llamafactory-cli train "${TRAIN_YAML}"
}

merge_action() {
  require_cmd llamafactory-cli
  prepare_action
  require_adapter_ready
  log "Merging LoRA adapter into standalone model"
  llamafactory-cli export "${MERGE_YAML}"
}

eval_action() {
  prepare_action
  log "Evaluating baseline model"
  "${PYTHON_BIN}" "${WORK_DIR}/evaluate_model.py" "${MODEL_PATH}" "${RUNTIME_DATA_DIR}/${EVAL_DATASET_FILE}" "${EVAL_BASELINE_DIR}"

  require_merged_ready
  log "Evaluating merged model"
  "${PYTHON_BIN}" "${WORK_DIR}/evaluate_model.py" "${MERGED_DIR}" "${RUNTIME_DATA_DIR}/${EVAL_DATASET_FILE}" "${EVAL_FINETUNED_DIR}"
}

api_action() {
  require_cmd llamafactory-cli
  prepare_action
  require_merged_ready
  log "Starting OpenAI-style API at ${API_HOST}:${API_PORT}"
  API_HOST="${API_HOST}" API_PORT="${API_PORT}" llamafactory-cli api "${INFER_YAML}"
}

case "${action}" in
  prepare)
    prepare_action
    ;;
  train)
    train_action
    ;;
  merge)
    merge_action
    ;;
  eval)
    eval_action
    ;;
  api)
    api_action
    ;;
  all)
    train_action
    merge_action
    eval_action
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    die "unknown action: ${action}"
    ;;
esac
