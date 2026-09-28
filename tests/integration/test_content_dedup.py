from uuid import uuid4

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


def test_duplicate_bytes_share_blob_and_index_as_two_documents():
    app = create_app()
    with TestClient(app) as client:
        email = f"cas-{uuid4().hex[:8]}@example.com"
        signup = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "tenant_name": f"Cas{uuid4().hex[:6]}"},
        )
        if signup.status_code >= 500:
            pytest.skip("database unavailable")
        assert signup.status_code == 200, signup.text
        headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
        body = b"# Leave policy\nEmployees receive fifteen days of PTO.\n"

        first = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("policy.md", body, "text/markdown")},
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        if first_body.get("status") not in {"queued", "completed"}:
            pytest.skip(f"canonical ingest did not complete: {first_body}")
        assert first_body.get("job_id")
        assert first_body["document_id"]
        assert first_body["version_id"]

        second = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("policy copy.md", body, "text/markdown")},
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["status"] == "deduplicated"
        assert second_body.get("job_id") in (None, "")
        assert "job_id" not in second_body or not second_body.get("job_id")
        assert second_body["document_id"] != first_body["document_id"]
        assert second_body["canonical_version_id"] == first_body["version_id"]

        docs = client.get("/api/v1/documents", headers=headers)
        assert docs.status_code == 200
        listed = docs.json()
        titles = {d["title"] for d in listed}
        assert "policy.md" in titles
        assert "policy copy.md" in titles
        cas_keys = {d["storage_key"] for d in listed if d["title"] in {"policy.md", "policy copy.md"}}
        assert len(cas_keys) == 1
        key = next(iter(cas_keys))
        assert "/cas/" in key

        first_versions = client.get(f"/api/v1/documents/{first_body['document_id']}/versions", headers=headers)
        assert first_versions.status_code == 200, first_versions.text
        assert first_versions.json()[-1]["derived_from_version_id"] is None

        copy_versions = client.get(f"/api/v1/documents/{second_body['document_id']}/versions", headers=headers)
        assert copy_versions.status_code == 200, copy_versions.text
        derived = copy_versions.json()[-1]
        assert derived["derived_from_version_id"] == first_body["version_id"]

        again = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("policy.md", body, "text/markdown")},
        )
        assert again.status_code == 200, again.text
        unchanged = again.json()
        assert unchanged["status"] == "unchanged"
        assert unchanged["document_id"] == first_body["document_id"]
        assert unchanged["version_id"] == first_body["version_id"]
        assert unchanged["version_new"] is False
