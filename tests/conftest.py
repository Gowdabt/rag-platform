from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def config_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path(__file__).resolve().parents[1]
    configs = root / "configs"
    monkeypatch.setenv("RAG_CONFIG_DIR", str(configs))
    monkeypatch.setenv("RAG_ENV", "development")
    monkeypatch.setenv("RAG_ALLOW_PUBLIC_SIGNUP", "1")
    monkeypatch.setenv("RAG_AUTH_RATE_LIMIT", "200")
    monkeypatch.setenv("RAG_AUTH_RATE_WINDOW", "60")
    return configs
