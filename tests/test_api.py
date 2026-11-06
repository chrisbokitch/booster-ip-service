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
    text = client.get("/api/v1/data", params={"output": "list", "sources": "heybox", "format": "ip", "offset": 2, "limit": 2})
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/plain")
    assert text.text == "192.0.2.2\n192.0.2.3\n"
    assert text.headers["x-total-count"] == "4"
    assert client.get("/api/v1/data.txt").status_code == 404
    assert text.headers["x-data-complete"] == "true"
    assert text.headers["x-has-more"] == "false"
    assert text.headers["x-next-offset"] == ""


def test_export_validates_sources_and_limits(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    assert client.get("/api/v1/data", params={"output": "list", "sources": "missing"}).status_code == 404
    assert client.get("/api/v1/data", params={"output": "list", "limit": 1000001}).status_code == 422
    assert client.get("/api/v1/data", params={"output": "list", "sources": " "}).status_code == 422
    response = client.get("/api/v1/data", params={"output": "list"})
    assert response.status_code == 200
    assert response.text == ""
    assert response.headers["x-data-complete"] == "false"

def test_custom_limit_over_ten_thousand(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("heybox", "10.0.0.0/18"))
    client = TestClient(main.app)
    response = client.get("/api/v1/data", params={"sources": "heybox", "format": "ip", "limit": 12000})
    assert response.status_code == 200
    assert response.json()["count"] == 12000
    assert response.json()["has_more"] is True


def test_output_parameter_validation(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    assert client.get("/api/v1/data", params={"output": "csv"}).status_code == 422
    assert client.get("/api/v1/data").headers["content-type"].startswith("application/json")
    assert "/api/v1/data.txt" not in {route.path for route in main.app.routes}


def test_source_management_is_config_only(tmp_path, monkeypatch):
    from app.config import load_source_config
    from app.core import sync_source_config
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    schema = client.get("/openapi.json").json()
    routes = schema["paths"]
    assert "post" not in routes["/api/v1/sources"]
    assert "/api/v1/sources/{source_id}" not in routes
    assert client.post("/api/v1/sources", json={}).status_code == 405
    assert client.put("/api/v1/sources/heybox", json={}).status_code == 405
    assert client.delete("/api/v1/sources/heybox").status_code == 405
    assert client.get("/api/v1/sources").status_code == 200
    assert len(load_source_config()) == 2
    sync_source_config(path, load_source_config())


def test_config_change_invalidates_snapshot_and_preserves_history(tmp_path):
    from app.config import SourceDefinition
    from app.core import sync_source_config
    path = tmp_path / "service.db"
    init_db(path)
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("heybox", "192.0.2.0/24"))
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='heybox'")
        db.execute("INSERT INTO refresh_history(source_id,at,success,count) VALUES ('heybox','2026-11-05',1,1)")
    changed = SourceDefinition(id="heybox", name="HEYBOX", url="https://example.com/updated", format="ip_text")
    sync_source_config(path, [changed])
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE source_id='heybox'").fetchone()[0] == 0
        assert db.execute("SELECT last_success FROM sources WHERE id='heybox'").fetchone()[0] is None
        assert db.execute("SELECT COUNT(*) FROM refresh_history WHERE source_id='heybox'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
