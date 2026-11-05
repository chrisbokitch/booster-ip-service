from fastapi.testclient import TestClient
from app import main
from app.core import init_db, connect


def test_json_pagination_and_text_export(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("heybox", "192.0.2.0/30"))
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='heybox'")
    client = TestClient(main.app)
    response = client.get("/api/v1/data", params={"sources": "heybox", "format": "ip", "limit": 2})
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 4
    assert result["has_more"] is True
    assert result["next_offset"] == 2
    text = client.get("/api/v1/data.txt", params={"sources": "heybox", "format": "ip", "offset": 2, "limit": 2})
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    assert text.text == "192.0.2.2\n192.0.2.3\n"
    assert text.headers["x-total-count"] == "4"
    assert text.headers["x-data-complete"] == "true"
    assert text.headers["x-has-more"] == "false"
    assert text.headers["x-next-offset"] == ""


def test_export_validates_sources_and_limits(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    assert client.get("/api/v1/data.txt", params={"sources": "missing"}).status_code == 404
    assert client.get("/api/v1/data.txt", params={"limit": 10001}).status_code == 422
    assert client.get("/api/v1/data.txt", params={"sources": " "}).status_code == 422
    response = client.get("/api/v1/data.txt")
    assert response.status_code == 200
    assert response.text == ""
    assert response.headers["x-data-complete"] == "false"
