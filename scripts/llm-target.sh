#!/usr/bin/env bash
# Point every surface at one inference lane — this app (host) and sojourner's tiers.
#
#   scripts/llm-target.sh local
#   scripts/llm-target.sh rented http://gpu-box:8000/v1 qwen3-coder:30b
#   scripts/llm-target.sh claude  claude-opus-5,claude-sonnet-5
#   scripts/llm-target.sh hybrid  http://gpu-box:8000/v1 qwen3-coder:30b
#
# Embeddings (bge-m3) and the vision model (qwen3-vl) are local models and are
# NEVER moved by this script — only chat changes lane.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
ENV_FILE=.env
# Sojourner's tier env files, when the sibling checkout is there
SOJOURNER="${SOJOURNER_DIR:-../sojourner}"
T1="$SOJOURNER/infra/compose/tier1.env"
T2="$SOJOURNER/infra/compose/tier2.env"
ST="$SOJOURNER/infra/compose/staging.env"   # the deployed app follows the lane too

usage() { sed -n '2,12p' "$0" >&2; exit 2; }
[ -n "$MODE" ] || usage
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"

# set_kv <file> <key> <value>   — replace in place, or append if absent
set_kv() {
  local f="$1" k="$2" v="$3"
  if grep -qE "^${k}=" "$f"; then
    # value may contain slashes; use a non-slash delimiter
    sed -i.bak -E "s|^${k}=.*|${k}=${v}|" "$f" && rm -f "$f.bak"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}

case "$MODE" in
  local)
    CHAT="http://localhost:11434/v1"; KEY="ollama"; MODELS=""; DEFAULT="qwen3:8b"
    UPSTREAM="host.docker.internal:11434"; TIER_URL="http://llm-proxy:11434/v1"; TIER_KEY="ollama"
    ;;
  rented|hybrid)
    CHAT="${2:-}"; MODELS="${3:-}"
    [ -n "$CHAT" ] || { echo "error: $MODE needs a URL, e.g. http://gpu-box:8000/v1" >&2; usage; }
    KEY="${LLM_API_KEY:-vllm}"; DEFAULT="${MODELS%%,*}"
    # socat dials host:port — strip scheme and path off the chat URL
    hostport="${CHAT#http://}"; hostport="${hostport#https://}"; hostport="${hostport%%/*}"
    case "$hostport" in *:*) : ;; *) hostport="$hostport:8000" ;; esac
    UPSTREAM="$hostport"; TIER_URL="http://llm-proxy:11434/v1"; TIER_KEY="$KEY"
    case "$CHAT" in https://*) echo "WARNING: socat cannot terminate TLS — put the endpoint behind the litellm gateway or use plain HTTP on a private network." >&2 ;; esac
    ;;
  claude)
    MODELS="${2:-claude-opus-5,claude-sonnet-5}"; DEFAULT="${MODELS%%,*}"
    CHAT="http://localhost:4000/v1"; KEY="${LITELLM_MASTER_KEY:-horizons-gateway-key}"
    UPSTREAM="host.docker.internal:11434"    # unused by this lane
    TIER_URL="http://litellm:4000/v1"; TIER_KEY="$KEY"
    : "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY (it lives in the gateway, never in agent code)}"
    ;;
  *) usage ;;
esac

set_kv "$ENV_FILE" LLM_PROVIDER "$MODE"
set_kv "$ENV_FILE" LLM_BASE_URL "$CHAT"
set_kv "$ENV_FILE" LLM_API_KEY "$KEY"
set_kv "$ENV_FILE" LLM_MODELS "$MODELS"
set_kv "$ENV_FILE" LLM_MODEL_DEFAULT "$DEFAULT"
set_kv "$ENV_FILE" OLLAMA_HOST "http://localhost:11434"
set_kv "$ENV_FILE" LLM_UPSTREAM "$UPSTREAM"

# Inside a tier LLM_BASE_URL is the proxy (or the gateway) on EVERY lane, so
# the tier is told the lane and where it really goes — its Inference screen
# must never imply local inference on a remote lane.
case "$MODE" in
  local) LANE_URL="http://host.docker.internal:11434/v1" ;;
  *)     LANE_URL="$CHAT" ;;
esac
for f in "$T1" "$T2" "$ST"; do
  [ -f "$f" ] || continue
  set_kv "$f" LLM_BASE_URL "$TIER_URL"
  set_kv "$f" LLM_API_KEY "$TIER_KEY"
  set_kv "$f" LLM_PROVIDER "$MODE"
  set_kv "$f" LLM_LANE_URL "$LANE_URL"
done
for f in "$T2" "$ST"; do [ -f "$f" ] && set_kv "$f" LLM_MODEL_DEFAULT "$DEFAULT"; done

cat <<EOF

lane: $MODE
  app (host)     chat  -> $CHAT
  sojourner (tiers + staging)  chat  -> $TIER_URL
  proxy upstream       -> $UPSTREAM
  models               -> ${MODELS:-<local registry>}   default: $DEFAULT
  embeddings + VLM     -> http://localhost:11434  (unchanged, local by design)

restart what is running:
  this app: restart 'make demo1'
  sojourner:    make demo2-down && make demo2-up   (in $SOJOURNER)$([ "$MODE" = claude ] && echo "   (claude lane: add --profile claude)")
EOF
