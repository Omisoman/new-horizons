"""ChatOpenAI factory + model registry.

Every LLM call in every agent goes through the OpenAI-compatible endpoint.
Local = Ollama on the Mac host (Metal). Production = vLLM on NVIDIA — swap
LLM_BASE_URL, nothing else. num_ctx=8192 is enforced server-side
(OLLAMA_CONTEXT_LENGTH; vLLM: --max-model-len).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from openai import OpenAI

from new_horizons.shared.llm import provider


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    arabic: str          # qualitative: strong | weak
    native_tools: bool   # informational only — the harness NEVER relies on it
    reasoning: bool      # emits <think> blocks the protocol parser must strip
    extra_body: dict = field(default_factory=dict)


REGISTRY: dict[str, ModelSpec] = {
    # reasoning_effort "none" is the knob Ollama's OpenAI endpoint honors:
    # it fully disables qwen3 thinking and attenuates deepseek-r1's
    # (deepseek cannot switch it off entirely — the protocol parser strips
    # whatever leaks).
    "qwen3:8b": ModelSpec(
        name="qwen3:8b", label="Qwen3 8B", arabic="strong",
        native_tools=True, reasoning=True,
        extra_body={"reasoning_effort": "none"},
    ),
    "llama3.1:8b": ModelSpec(
        name="llama3.1:8b", label="Llama 3.1 8B", arabic="weak",
        native_tools=True, reasoning=False,
    ),
    "deepseek-r1:8b": ModelSpec(
        name="deepseek-r1:8b", label="DeepSeek-R1 8B", arabic="weak",
        native_tools=False, reasoning=True,
        extra_body={"reasoning_effort": "none"},
    ),
}

CHAT_MODELS = list(REGISTRY)


def base_url() -> str:
    return provider.chat_base_url()


def api_key() -> str:
    return provider.chat_api_key()


def chat_models() -> list[str]:
    """Models the active lane offers (see shared/llm/provider.py)."""
    return provider.chat_models() or CHAT_MODELS


def chat_model(model: str | None = None, temperature: float = 0.1) -> ChatOpenAI:
    """LangChain chat model bound to the OpenAI-compatible endpoint."""
    name = model or os.environ.get("LLM_MODEL_DEFAULT", "qwen3:8b")
    spec = REGISTRY.get(name)
    extra = dict(spec.extra_body) if spec else {}
    return ChatOpenAI(
        model=name,
        base_url=base_url(),
        api_key=api_key(),
        temperature=temperature,
        extra_body=extra or None,
        timeout=180,
    )


def raw_client() -> OpenAI:
    """Bare OpenAI client (VLM structuring, embeddings via /api on Ollama)."""
    return OpenAI(base_url=base_url(), api_key=api_key())


def ollama_host() -> str:
    """Native Ollama API root (embeddings + keep_alive control).

    ALWAYS local: bge-m3 and qwen3-vl are laptop models, so this must not
    follow the chat endpoint when chat moves to a rented box or Claude.
    """
    return provider.ollama_host()
