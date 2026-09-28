
from fastapi.testclient import TestClient


def test_health_is_unchanged_without_spa(monkeypatch):
    monkeypatch.delenv("RAG_SERVE_FRONTEND", raising=False)
    from app.main import create_app

    with TestClient(create_app()) as client:
        body = client.get("/api/v1/health").json()
    assert "status" in body


def test_desktop_spa_serves_ui_and_keeps_api(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>desktop-shell</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setenv("RAG_SERVE_FRONTEND", "1")
    monkeypatch.setenv("RAG_FRONTEND_DIST", str(dist))
    from app.main import create_app

    with TestClient(create_app()) as client:
        assert "desktop-shell" in client.get("/").text
        assert "desktop-shell" in client.get("/sources").text
        assert client.get("/assets/app.js").text == "console.log('ok')"
        assert client.get("/api/v1/health").status_code == 200
