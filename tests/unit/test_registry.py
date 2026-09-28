from app.core.errors import ProviderNotImplementedError
from app.domain.registry import ProviderRegistry, register, registry


def test_register_and_create_custom_registry():
    local = ProviderRegistry()

    class Dummy:
        def __init__(self, label: str):
            self.label = label

    local.register("llm", "dummy", Dummy)
    instance = local.create("llm", "dummy", "ok")
    assert instance.label == "ok"


def test_missing_provider_is_not_a_fake_success():
    local = ProviderRegistry()
    try:
        local.get("llm", "ollama")
        assert False, "expected ProviderNotImplementedError"
    except ProviderNotImplementedError as exc:
        assert "no registered implementation" in str(exc)


def test_decorator_registers_on_global_registry():
    @register("test_kind", "unit")
    class Marker:
        pass

    assert registry.contains("test_kind", "unit")
    assert registry.get("test_kind", "unit") is Marker
