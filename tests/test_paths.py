"""ROOT is the code, DATA is the generated data — and HORIZONS_DATA moves only
the data (sojourner runs a read-only deploy with its data on a volume)."""

import importlib


def _paths(monkeypatch, **env):
    for k in ("HORIZONS_DATA", "HORIZONS_HOME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    import new_horizons.paths as p
    return importlib.reload(p)


def test_the_checkout_holds_its_own_data_by_default(monkeypatch):
    p = _paths(monkeypatch)
    assert (p.ROOT / "pyproject.toml").exists() and p.DATA == p.ROOT / "data"
    assert p.data_path(None, "kb") == p.ROOT / "data" / "kb"


def test_horizons_data_moves_the_data_but_never_the_repo_files(monkeypatch, tmp_path):
    p = _paths(monkeypatch, HORIZONS_DATA=tmp_path / "farm")
    try:
        assert p.DATA == (tmp_path / "farm").resolve()
        assert (p.ROOT / "docs" / "question-set.yaml").exists()      # docs stay with the code
        assert p.data_path("data/kb", "kb") == p.DATA / "kb"          # .env's KB_DIR=data/kb follows
        assert p.data_path(None, "audit/audit.jsonl") == p.DATA / "audit" / "audit.jsonl"
        assert p.data_path("/abs/kb", "kb").as_posix() == "/abs/kb"
        assert p.data_path("tenants/acme-kb", "kb") == p.ROOT / "tenants" / "acme-kb"
    finally:
        _paths(monkeypatch)
