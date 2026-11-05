from fastapi.testclient import TestClient
from app import main
from app.core import connect, init_db


def test_manage_sources_and_snapshot_invalidation(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    payload = {"id": "customfeed", "name": "Custom", "url": "https://example.com/feed",
               "format": "cidr_text", "enabled": True}
    assert client.post("/api/v1/sources", json=payload).status_code == 201
    assert client.post("/api/v1/sources", json=payload).status_code == 409
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("customfeed", "192.0.2.0/24"))
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='customfeed'")
    changed = dict(payload, url="https://example.com/new", enabled=False)
    response = client.put("/api/v1/sources/customfeed", json=changed)
    assert response.status_code == 200
    assert response.json()["snapshot_cleared"] is True
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE source_id='customfeed'").fetchone()[0] == 0
        assert db.execute("SELECT last_success FROM sources WHERE id='customfeed'").fetchone()[0] is None
    assert client.delete("/api/v1/sources/customfeed").status_code == 204
    assert client.put("/api/v1/sources/customfeed", json=changed).status_code == 404
    assert client.delete("/api/v1/sources/customfeed").status_code == 404


def test_deleted_default_does_not_reappear(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    assert client.delete("/api/v1/sources/heybox").status_code == 204
    init_db(path)
    assert "heybox" not in [item["id"] for item in client.get("/api/v1/sources").json()]


def test_refresh_all_isolates_failures(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    calls = []
    def fake_refresh(db_path, source_id):
        calls.append(source_id)
        if source_id == "heybox":
            raise ValueError("offline")
        return {"count": 3}
    monkeypatch.setattr(main, "refresh_source", fake_refresh)
    response = TestClient(main.app).post("/api/v1/sources/refresh-all")
    assert response.status_code == 200
    assert response.json()["succeeded"] == 1
    assert response.json()["failed"] == 1
    assert calls == ["heybox", "uubooster"]

def test_edit_existing_heybox_with_json_path(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    source = next(item for item in client.get("/api/v1/sources").json()
                  if item["id"] == "heybox")
    payload = {"name": source["name"], "url": source["url"],
               "format": source["format"], "json_path": source["json_path"],
               "enabled": bool(source["enabled"])}
    response = client.put("/api/v1/sources/heybox", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_cleared"] is False

def test_scheduling_and_history(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from app.core import refresh_due_sources
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    source = next(x for x in client.get("/api/v1/sources").json() if x["id"] == "heybox")
    payload = {"name": source["name"], "url": source["url"], "format": source["format"],
               "json_path": source["json_path"], "enabled": True, "refresh_interval_minutes": 60}
    response = client.put("/api/v1/sources/heybox", json=payload)
    assert response.status_code == 200, response.text
    row = next(x for x in client.get("/api/v1/sources").json() if x["id"] == "heybox")
    assert row["refresh_interval_minutes"] == 60
    assert row["next_refresh"] is not None
    with connect(path) as db:
        db.execute("UPDATE sources SET next_refresh=? WHERE id='heybox'",
                   ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        db.execute("INSERT INTO refresh_history(source_id,at,success,count) VALUES (?,?,1,?)",
                   ("heybox", datetime.now(timezone.utc).isoformat(), 12))
    assert client.get("/api/v1/sources/heybox/history").json()[0]["count"] == 12
    assert client.get("/api/v1/sources/missing/history").status_code == 404
    assert client.put("/api/v1/sources/heybox", json=dict(payload, refresh_interval_minutes=0)).status_code == 422
    assert client.put("/api/v1/sources/heybox", json=dict(payload, refresh_interval_minutes=10081)).status_code == 422
    calls = []
    monkeypatch.setattr("app.core.refresh_source", lambda db, source_id: calls.append(source_id))
    refresh_due_sources(path)
    assert calls == ["heybox"]
    assert client.put("/api/v1/sources/heybox", json=dict(payload, enabled=False)).status_code == 200
    row = next(x for x in client.get("/api/v1/sources").json() if x["id"] == "heybox")
    assert row["next_refresh"] is None
