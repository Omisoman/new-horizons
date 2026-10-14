"""The inference lane switch — and the split that keeps demo 1 working.

The regression these guard: embeddings (bge-m3) and the vision model
(qwen3-vl) are LOCAL models, but every call site used to derive their URL by
stripping `/v1` off the chat endpoint. The moment chat moved to a rented GPU or
Claude, KB search and invoice intake would have followed it and broken.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from new_horizons.shared.llm import provider

ROOT = Path(__file__).parents[1]

LANE_ENV = ("LLM_PROVIDER", "LLM_BASE_URL", "OLLAMA_HOST", "LLM_MODELS",
            "LLM_MODEL_DEFAULT", "LLM_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in LANE_ENV:
        monkeypatch.delenv(key, raising=False)


def test_default_lane_is_local():
    assert provider.mode() == "local"
    assert provider.is_local_chat()
    assert provider.chat_base_url() == "http://localhost:11434/v1"


def test_unknown_lane_falls_back_instead_of_failing(monkeypatch):
    """A typo in LLM_PROVIDER must not take the demo down."""
    monkeypatch.setenv("LLM_PROVIDER", "clade")
    assert provider.mode() == "local"


@pytest.mark.parametrize("lane", ["rented", "claude", "hybrid"])
def test_embeddings_and_vlm_stay_local_when_chat_moves(monkeypatch, lane):
    monkeypatch.setenv("LLM_PROVIDER", lane)
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu-box:8000/v1")

    assert provider.chat_base_url() == "http://gpu-box:8000/v1"
    assert provider.ollama_host() == "http://localhost:11434"
    assert provider.is_local_chat() is False


def test_local_lane_still_derives_one_url(monkeypatch):
    """Single-endpoint setups keep working exactly as before."""
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LLM_BASE_URL", "http://otherhost:11434/v1")
    assert provider.ollama_host() == "http://otherhost:11434"


def test_pinned_ollama_host_wins(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LLM_BASE_URL", "http://otherhost:11434/v1")
    monkeypatch.setenv("OLLAMA_HOST", "http://pinned:11434/v1")
    assert provider.ollama_host() == "http://pinned:11434"


def test_remote_lane_lists_the_models_the_endpoint_serves(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("LLM_MODELS", "claude-opus-5, claude-sonnet-5")
    assert provider.chat_models() == ["claude-opus-5", "claude-sonnet-5"]


def test_local_lane_lists_the_curated_registry():
    from new_horizons.shared.llm.client import REGISTRY
    assert provider.chat_models() == list(REGISTRY)


def test_remote_lane_without_a_list_falls_back_to_the_default_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rented")
    monkeypatch.setenv("LLM_MODEL_DEFAULT", "qwen3-coder:30b")
    assert provider.chat_models() == ["qwen3-coder:30b"]


def test_describe_states_where_inference_runs(monkeypatch):
    """The UI and the runbook both need to say this out loud — a demo must
    never imply local inference while running somewhere else."""
    monkeypatch.setenv("LLM_PROVIDER", "rented")
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu-box:8000/v1")

    d = provider.describe()

    assert d["mode"] == "rented"
    assert "Dedicated" in d["label"]
    assert d["chat_base_url"] == "http://gpu-box:8000/v1"
    assert d["ollama_host"] == "http://localhost:11434"
    assert d["local_chat"] is False


def test_model_residency_is_only_a_local_concept(monkeypatch):
    """swap_model unloads/warms via Ollama — a no-op on remote lanes."""
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    calls = []
    monkeypatch.setattr("new_horizons.shared.llm.switch._ollama",
                        lambda *a, **k: calls.append(a))

    from new_horizons.shared.llm.switch import swap_model
    swap_model("claude-opus-5", "claude-sonnet-5")

    assert calls == []
