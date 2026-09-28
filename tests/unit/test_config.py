from app.config.load import (
    apply_overlays,
    load_platform_settings,
    load_yaml_layers,
    parse_settings,
)
from app.config.merge import assert_overlay_allowed, deep_merge
from app.core.errors import ConfigError, OverlayDeniedError, UnknownProviderError


def test_deep_merge_nested_and_replaces_lists():
    base = {"llm": {"provider": "ollama", "model": "a"}, "tags": [1]}
    overlay = {"llm": {"model": "b"}, "tags": [2, 3]}
    merged = deep_merge(base, overlay)
    assert merged["llm"]["provider"] == "ollama"
    assert merged["llm"]["model"] == "b"
    assert merged["tags"] == [2, 3]


def test_development_yaml_loads_offline_defaults():
    settings = load_platform_settings(resolve=False)
    assert settings.llm.provider == "ollama"
    assert settings.embedding.provider == "ollama"
    assert settings.embedding.model == "nomic-embed-text"
    assert settings.vector_store.provider == "pgvector"
    assert settings.sparse_index.provider == "postgres_fts"
    assert settings.privacy.store_llm_prompts is False
    assert settings.platform.environment == "development"


def test_unknown_provider_fails_validation():
    data = load_yaml_layers("development")
    data["vector_store"]["provider"] = "unknown"
    try:
        parse_settings(data)
        raised = False
    except UnknownProviderError:
        raised = True
    except ConfigError as exc:
        raised = "Unknown" in str(exc)
    assert raised


def test_chunk_overlap_must_be_less_than_size():
    data = load_yaml_layers("development")
    data["chunking"]["chunk_size"] = 100
    data["chunking"]["chunk_overlap"] = 100
    try:
        parse_settings(data)
        assert False, "expected ConfigError"
    except ConfigError:
        pass


def test_tenant_overlay_can_change_llm_provider():
    settings = load_platform_settings(
        overlays=[("tenant", {"llm": {"provider": "openai", "model": "gpt-4.1"}})],
        resolve=False,
    )
    assert settings.llm.provider == "openai"


def test_user_cannot_change_provider():
    try:
        assert_overlay_allowed({"llm": {"provider": "openai"}}, "user")
        assert False, "expected OverlayDeniedError"
    except OverlayDeniedError:
        pass


def test_user_can_set_temperature():
    assert_overlay_allowed({"llm": {"temperature": 0.2}}, "user")
    settings = load_platform_settings(
        overlays=[("user", {"llm": {"temperature": 0.2}})],
        resolve=False,
    )
    assert settings.llm.temperature == 0.2


def test_request_cannot_set_privacy():
    try:
        apply_overlays({}, [("request", {"privacy": {"store_queries": False}})])
        assert False, "expected OverlayDeniedError"
    except OverlayDeniedError:
        pass


def test_request_cannot_set_tenant_id():
    try:
        assert_overlay_allowed({"tenant_id": "abc"}, "tenant")
        assert False, "expected OverlayDeniedError"
    except OverlayDeniedError:
        pass
