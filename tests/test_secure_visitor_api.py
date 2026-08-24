from fastapi.testclient import TestClient

from jarvis_home.app import app, cfg


def test_visitor_history_and_media_require_admin_authentication():
    client = TestClient(app)
    assert client.get("/api/visitors").status_code == 401
    assert client.get("/api/visitors/unknown/media/thumbnail").status_code == 401
    assert client.get("/api/front-door/preview.jpg").status_code == 401


def test_visitor_api_never_returns_filesystem_paths():
    client = TestClient(app)
    response = client.get(
        "/api/visitors", headers={"X-Jarvis-Token": cfg.jarvis_admin_token}
    )
    assert response.status_code == 200
    for visitor in response.json():
        assert "visitor_photo" not in visitor
        assert "badge_photo" not in visitor
        assert all("/Users/" not in str(value) for value in visitor.values())


def test_unknown_media_identifier_cannot_read_arbitrary_file():
    client = TestClient(app)
    response = client.get(
        "/api/visitors/not-a-real-visitor/media/snapshot",
        headers={"X-Jarvis-Token": cfg.jarvis_admin_token},
    )
    assert response.status_code == 404
