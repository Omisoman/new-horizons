# Source this before `ollama serve` on the Mac (16 GB budget).
#   source scripts/ollama-env.sh && ollama serve
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_MAX_LOADED_MODELS=2
export OLLAMA_KEEP_ALIVE=10m
# Enforces the num_ctx=8192 rule globally: the OpenAI-compatible endpoint
# ignores per-request `options`, so the server default IS the contract.
export OLLAMA_CONTEXT_LENGTH=8192
# Containers reach the host at host.docker.internal — ollama must listen
# beyond loopback for Sojourner's tiers (host firewall still applies on the LAN).
export OLLAMA_HOST=0.0.0.0
