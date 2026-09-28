from pathlib import Path
from uuid import uuid4

import pytest
from app.adapters.providers.connectors.local_fs import resolve_allowed_path
from app.core.errors import ValidationFailedError
from app.main import create_app
from fastapi.testclient import TestClient


def test_local_fs_rejects_path_traversal_and_symlink_escape(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "ok.md").write_text("inside\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("escaped\n", encoding="utf-8")
    link = allowed / "escape-link"
    link.symlink_to(outside)

    monkeypatch.setenv("CONNECTOR_FS_ROOTS", str(allowed))

    with pytest.raises(ValidationFailedError):
        resolve_allowed_path(str(allowed / ".." / "outside"), extra=[str(allowed)], isolation="host")
    with pytest.raises(ValidationFailedError):
        resolve_allowed_path(str(link), extra=[str(allowed)], isolation="host")

    app = create_app()
    with TestClient(app) as client:
        email = f"fs-esc-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"Esc{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
        created = client.post(
            "/api/v1/connectors",
            headers=headers,
            json={"connector_type": "local_fs", "name": "Escape", "connector_config": {"root_path": str(allowed)}},
        )
        assert created.status_code == 200, created.text
        source_id = created.json()["id"]

        traversal = client.get(
            f"/api/v1/connectors/{source_id}/locations/{allowed / '..' / 'outside'!s}/children",
            headers=headers,
        )
        assert traversal.status_code in {400, 404, 422}

        browse = client.get(
            "/api/v1/connectors/local-fs/browse",
            headers=headers,
            params={"path": str(link)},
        )
        assert browse.status_code in {400, 404, 422}
        if browse.status_code == 200:
            assert "secret.md" not in browse.text
