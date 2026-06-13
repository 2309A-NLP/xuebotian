#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="/opt/ragflow"
REPO_DIR="${1:-$DEFAULT_REPO_DIR}"
RESTART_MODE="${2:-docker}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$REPO_DIR/backups/vl_prompt_optimization_$TIMESTAMP"

PROMPT_DIR="$REPO_DIR/rag/prompts"
DESCRIBE_PROMPT="$PROMPT_DIR/vision_llm_describe_prompt.md"
FIGURE_PROMPT="$PROMPT_DIR/vision_llm_figure_describe_prompt.md"
FIGURE_CTX_PROMPT="$PROMPT_DIR/vision_llm_figure_describe_prompt_with_context.md"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2
  exit 1
}

check_file() {
  local f="$1"
  [[ -f "$f" ]] || fail "Missing file: $f"
}

restart_services() {
  case "$RESTART_MODE" in
    docker)
      if [[ -f "$REPO_DIR/docker/docker-compose.yml" ]]; then
        log "Restarting services with docker compose"
        docker compose -f "$REPO_DIR/docker/docker-compose.yml" restart
      else
        log "docker-compose.yml not found, skip restart"
      fi
      ;;
    none)
      log "Skip restart because RESTART_MODE=none"
      ;;
    *)
      fail "Unsupported restart mode: $RESTART_MODE. Use docker or none."
      ;;
  esac
}

log "Repo dir: $REPO_DIR"
log "Restart mode: $RESTART_MODE"

[[ -d "$REPO_DIR" ]] || fail "Repo directory does not exist: $REPO_DIR"
[[ -d "$PROMPT_DIR" ]] || fail "Prompt directory does not exist: $PROMPT_DIR"

check_file "$DESCRIBE_PROMPT"
check_file "$FIGURE_PROMPT"
check_file "$FIGURE_CTX_PROMPT"

mkdir -p "$BACKUP_DIR"
cp -f "$DESCRIBE_PROMPT" "$BACKUP_DIR/"
cp -f "$FIGURE_PROMPT" "$BACKUP_DIR/"
cp -f "$FIGURE_CTX_PROMPT" "$BACKUP_DIR/"

log "Backups created in: $BACKUP_DIR"

cat > "$DESCRIBE_PROMPT" <<'EOF'
## ROLE

You are a document transcription engine for RAG indexing.

## GOAL

Transcribe the visible content from the provided document page image into clean Markdown that preserves the original reading order and structure as closely as possible.

## HARD RULES

1. Only output content that is explicitly visible in the image.
2. Do not infer, summarize, explain, translate, correct, or rewrite the content.
3. If a word, number, or symbol is unreadable, do not guess it.
4. Do not output this instruction or any extra commentary.
5. Do not wrap the output in code fences.

## STRUCTURE RULES

1. Preserve headings, paragraphs, bullet lists, numbered lists, and tables only when they are visibly present.
2. Preserve the original language and reading order.
3. Keep figure titles, table titles, captions, footnotes, page headers, and page footers if they are visible and legible.
4. If part of the page is unreadable, continue transcribing the readable parts.
5. Do not create a table unless the image clearly shows a table structure.
6. Do not convert ordinary aligned text into a table.

## FAILURE RULE

If the page contains no readable textual content at all, return an empty string.

{% if page %}
At the end of the transcription, add the page divider: `--- Page {{ page }} ---`.
{% endif %}
EOF

cat > "$FIGURE_PROMPT" <<'EOF'
## ROLE

You are a visual evidence extraction engine for RAG indexing.

## GOAL

Analyze the image and output only information that is directly supported by visible evidence in the image.

## DECISION RULE

First determine whether the image contains an explicit visual dataset made of enumerable units intended for comparison, measurement, or aggregation.

Examples include:

- table rows or columns
- bars in a bar chart
- points or series in a line chart
- labeled segments in a pie chart
- heatmap cells with readable labels or values

Numbers, icons, screenshots, and labels alone do not qualify unless they form such a dataset.

## GLOBAL RULES

1. Output exactly one mode.
2. Do not explain which mode you chose.
3. Do not infer intent, causality, process meaning, functionality, or conclusions.
4. If a value or label is not clearly readable, mark it as `Unreadable` or `Uncertain` instead of guessing.
5. Do not use surrounding knowledge that is not visible in the image.

## MODE A: STRUCTURED VISUAL DATA

Use this mode only when the image contains a chart, graph, table, or other explicit visual dataset.

Output only these fields:

- Visual Type:
- Title:
- Axes / Legends / Labels:
- Data Points:
- Captions / Annotations:
- Unreadable or Uncertain Parts:

Requirements:

1. `Visual Type` must be concise, such as `bar chart`, `line chart`, `table`, `pie chart`, `scatter plot`.
2. `Title` should contain only visible title text.
3. `Axes / Legends / Labels` should list visible axis names, units, legend names, category labels, and series labels.
4. `Data Points` should include only values or comparisons that are directly readable.
5. If exact values are not readable but relative ordering is visible, state only the visible ordering.
6. Do not fabricate missing values.

## MODE B: GENERAL FIGURE CONTENT

Use this mode when the image is not an explicit visual dataset.

Write compact evidence-based prose with the following priorities:

1. overall layout first
2. major visible regions or objects
3. visible labels and text
4. spatial relationships
5. numbered markers, arrows, connectors, or callouts

Requirements:

1. Follow a stable order such as top-to-bottom and left-to-right.
2. Name interface elements exactly as they appear when the image is a UI screenshot.
3. For diagrams or flow-like images, describe only explicitly visible nodes, connectors, and labels.
4. For photos or illustrations, describe only clearly visible objects and text.
5. Do not call the image a chart, process, workflow, phase, or sequence unless that wording is visible in the image.
6. Do not use bullet lists in this mode.
EOF

cat > "$FIGURE_CTX_PROMPT" <<'EOF'
## ROLE

You are a visual evidence extraction engine for RAG indexing.

## GOAL

Analyze the image and output only information that is directly supported by visible evidence in the image.
Surrounding context may be used only to disambiguate terms that are already visible in the image.

## CONTEXT ABOVE

{{ context_above }}

## CONTEXT BELOW

{{ context_below }}

## DECISION RULE

First determine whether the image contains an explicit visual dataset made of enumerable units intended for comparison, measurement, or aggregation.

Examples include:

- table rows or columns
- bars in a bar chart
- points or series in a line chart
- labeled segments in a pie chart
- heatmap cells with readable labels or values

Numbers, icons, screenshots, and labels alone do not qualify unless they form such a dataset.

## GLOBAL RULES

1. Output exactly one mode.
2. Do not explain which mode you chose.
3. Context may clarify abbreviations or terms that are visible in the image, but may not add new facts that are absent from the image.
4. Do not infer intent, causality, process meaning, functionality, or conclusions.
5. If a value or label is not clearly readable, mark it as `Unreadable` or `Uncertain` instead of guessing.

## MODE A: STRUCTURED VISUAL DATA

Use this mode only when the image contains a chart, graph, table, or other explicit visual dataset.

Output only these fields:

- Visual Type:
- Title:
- Axes / Legends / Labels:
- Data Points:
- Captions / Annotations:
- Unreadable or Uncertain Parts:

Requirements:

1. `Visual Type` must be concise.
2. `Title` should contain only visible title text.
3. `Axes / Legends / Labels` should list visible axis names, units, legend names, category labels, and series labels.
4. `Data Points` should include only values or comparisons that are directly readable.
5. If exact values are not readable but relative ordering is visible, state only the visible ordering.
6. Do not fabricate missing values from context.

## MODE B: GENERAL FIGURE CONTENT

Use this mode when the image is not an explicit visual dataset.

Write compact evidence-based prose with the following priorities:

1. overall layout first
2. major visible regions or objects
3. visible labels and text
4. spatial relationships
5. numbered markers, arrows, connectors, or callouts

Requirements:

1. Follow a stable order such as top-to-bottom and left-to-right.
2. Name interface elements exactly as they appear when the image is a UI screenshot.
3. For diagrams or flow-like images, describe only explicitly visible nodes, connectors, and labels.
4. For photos or illustrations, describe only clearly visible objects and text.
5. Do not use context to assert invisible content.
6. Do not use bullet lists in this mode.
EOF

log "Prompt templates updated"
restart_services
log "Deployment finished successfully"
log "If needed, restore from backup directory: $BACKUP_DIR"
