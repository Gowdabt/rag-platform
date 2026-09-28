from uuid import uuid4

from app.application.factory import ProviderFactory
from app.config.load import load_platform_settings
from app.core.context import RequestContext
from app.core.errors import ProviderNotImplementedError, UnknownProviderError
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_endpoint():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["providers"]["llm"] == "ollama"
    assert body["providers"]["embedding"] == "ollama"
    assert "ollama" in body


def test_factory_unknown_kind():
    settings = load_platform_settings(resolve=False)
    factory = ProviderFactory(settings, RequestContext(request_id="t", tenant_id=uuid4()))
    try:
        factory.create("not_a_kind")
        assert False
    except UnknownProviderError:
        pass


def test_factory_known_but_unimplemented():
    from app.application.providers import load_providers

    load_providers()
    settings = load_platform_settings(resolve=False)
    factory = ProviderFactory(settings, RequestContext(request_id="t", tenant_id=uuid4()))
    try:
        factory.create("vector_store", "pinecone", config=settings.vector_store, ctx=RequestContext(request_id="t"))
        assert False, "pinecone is an extension point, not implemented"
    except ProviderNotImplementedError:
        pass
