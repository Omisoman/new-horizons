"""Where inference runs — one switch for every surface.

Four lanes, ONE contract: the code only ever speaks to an OpenAI-compatible
endpoint (the repo's hard rule), so Claude is reached through a gateway that
presents that surface — never a provider SDK in agent code.

    local    chat on host Ollama (Metal)            the laptop demo
    rented   chat on vLLM over an OpenAI endpoint   rented / dedicated GPU
    claude   chat on Claude through a LiteLLM gateway
    hybrid   chat remote, embeddings + VLM local    the data-residency split

TWO endpoints, not one. Embeddings (bge-m3) and the vision model (qwen3-vl)
are local-only models and ALWAYS resolve to the Ollama host. Deriving their
URL by stripping `/v1` off the chat endpoint — which is what every call site
used to do — silently broke KB search and invoice intake the moment chat moved
off the laptop. `hybrid` is that split made explicit; every other mode keeps it
too.

Env:
    LLM_PROVIDER      local | rented | claude | hybrid   (default: local)
    LLM_BASE_URL      chat endpoint, OpenAI-compatible
    LLM_API_KEY       chat credential ("ollama" locally)
    LLM_MODEL_DEFAULT model id the surfaces start on
    LLM_MODELS        comma-separated ids offered in the switch (remote lanes)
    OLLAMA_HOST       native Ollama root for embeddings + VLM
"""

from __future__ import annotations

import os

LOCAL = "local"
RENTED = "rented"
CLAUDE = "claude"
HYBRID = "hybrid"
MODES = (LOCAL, RENTED, CLAUDE, HYBRID)

DEFAULT_OLLAMA = "http://localhost:11434"
DEFAULT_CHAT = f"{DEFAULT_OLLAMA}/v1"

LABELS = {
    LOCAL: "Local · Ollama",
    RENTED: "Dedicated · vLLM",
    CLAUDE: "Claude · API",
    HYBRID: "Hybrid · remote chat, local embeddings",
}


def mode() -> str:
    """The active lane. An unknown value falls back to local rather than
    failing a demo on a typo."""
    value = os.environ.get("LLM_PROVIDER", LOCAL).strip().lower()
    return value if value in MODES else LOCAL


def is_local_chat() -> bool:
    """True when chat runs on the laptop's Ollama — the only case where model
    residency (load / unload / keep_alive) is a real concept."""
    return mode() == LOCAL


def chat_base_url() -> str:
    return os.environ.get("LLM_BASE_URL", DEFAULT_CHAT)


def chat_api_key() -> str:
    return os.environ.get("LLM_API_KEY", "ollama")


def ollama_host() -> str:
    """Native Ollama API root — embeddings, the vision model, keep_alive.

    Pinned by OLLAMA_HOST. Only when chat itself is local do we fall back to
    deriving it from the chat endpoint (which keeps single-URL setups working
    exactly as before).
    """
    pinned = os.environ.get("OLLAMA_HOST", "").strip()
    if pinned:
        return pinned.removesuffix("/v1").rstrip("/")
    if is_local_chat():
        return chat_base_url().removesuffix("/v1").rstrip("/")
    return DEFAULT_OLLAMA


def chat_models() -> list[str]:
    """Model ids the switch offers. Local lanes use the curated registry;
    remote lanes are whatever the endpoint serves (LLM_MODELS)."""
    listed = [m.strip() for m in os.environ.get("LLM_MODELS", "").split(",") if m.strip()]
    if listed:
        return listed
    if is_local_chat():
        from new_horizons.shared.llm.client import REGISTRY
        return list(REGISTRY)
    default = os.environ.get("LLM_MODEL_DEFAULT", "").strip()
    return [default] if default else []


def label() -> str:
    return LABELS.get(mode(), mode())


def describe() -> dict:
    """What a UI or a runbook needs to state plainly where inference ran."""
    return {
        "mode": mode(),
        "label": label(),
        "chat_base_url": chat_base_url(),
        "ollama_host": ollama_host(),
        "local_chat": is_local_chat(),
        "models": chat_models(),
    }
