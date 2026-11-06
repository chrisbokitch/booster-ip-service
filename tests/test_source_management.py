from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import SourceDefinition
from app.core import connect, init_db, refresh_due_sources, sync_source_config


def test_config_reconciliation_adds_updates_and_removes_sources(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    original = SourceDefinition(id="customfeed", name="Custom", url="https://example.com/feed", format="cidr_text")
    sync_source_config(path, [original])
    assert [row["id"] for row in client.get("/api/v1/sources").json()] == ["customfeed"]
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("customfeed", "192.0.2.0/24"))
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='customfeed'")
    renamed = original.model_copy(update={"name": "Renamed"})
    sync_source_config(path, [renamed])
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE source_id='customfeed'").fetchone()[0] == 1
    changed = original.model_copy(update={"url": original.url.__class__("https://example.com/new"), "enabled": False})
    sync_source_config(path, [changed])
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE source_id='customfeed'").fetchone()[0] == 0
        assert db.execute("SELECT last_success FROM sources WHERE id='customfeed'").fetchone()[0] is None
    sync_source_config(path, [])
    assert client.get("/api/v1/sources").json() == []
    assert client.post("/api/v1/sources", json={}).status_code == 405
    assert client.put("/api/v1/sources/customfeed", json={}).status_code == 404
    assert client.delete("/api/v1/sources/customfeed").status_code == 404


def test_removed_source_stays_removed_after_reconciliation(tmp_path):
    path = tmp_path / "service.db"
    init_db(path)
    sync_source_config(path, [])
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


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


def test_json_source_path_is_preserved(tmp_path):
    path = tmp_path / "service.db"
    init_db(path)
    with connect(path) as db:
        row = db.execute("SELECT format,json_path FROM sources WHERE id='heybox'").fetchone()
        assert row["format"] == "json"
        assert row["json_path"] == "result.ips"


def test_scheduling_and_history(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))
    client = TestClient(main.app)
    configured = SourceDefinition(id="heybox", name="HEYBOX", url="https://api.xiaoheihe.cn/heyboxaccip",
                                  format="json", json_path="result.ips", refresh_interval_minutes=60)
    sync_source_config(path, [configured])
    row = client.get("/api/v1/sources").json()[0]
    assert row["refresh_interval_minutes"] == 60
    assert row["next_refresh"] is not None
    with connect(path) as db:
        db.execute("UPDATE sources SET next_refresh=? WHERE id='heybox'",
                   ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        db.execute("INSERT INTO refresh_history(source_id,at,success,count) VALUES (?,?,1,?)",
                   ("heybox", datetime.now(timezone.utc).isoformat(), 12))
    assert client.get("/api/v1/sources/heybox/history").json()[0]["count"] == 12
    assert client.get("/api/v1/sources/missing/history").status_code == 404
    calls = []
    monkeypatch.setattr("app.core.refresh_source", lambda db, source_id, *, trigger="manual": calls.append((source_id, trigger)))
    refresh_due_sources(path)
    assert calls == [("heybox", "scheduled")]
    sync_source_config(path, [configured.model_copy(update={"enabled": False})])
    assert client.get("/api/v1/sources").json()[0]["next_refresh"] is None
