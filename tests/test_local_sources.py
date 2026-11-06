import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import SourceDefinition, load_source_config
from app.core import connect, init_db, refresh_source, sync_source_config


def test_local_file_ingestion_and_country_metadata(tmp_path, monkeypatch):
    feed = tmp_path / "manual.txt"
    feed.write_text("192.0.2.0/24\\n198.51.100.0/24\\n", encoding="utf-8")
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{
        "id": "manualfeed", "name": "Manual feed", "file_path": "manual.txt",
        "format": "cidr_text", "cntry_origin": "US", "enabled": True
    }]}), encoding="utf-8")
    definitions = load_source_config(config)
    assert definitions[0].file_path == str(feed.resolve())
    db_path = tmp_path / "service.db"
    init_db(db_path)
    sync_source_config(db_path, definitions)
    monkeypatch.setattr(main, "DB_PATH", str(db_path))
    result = refresh_source(db_path, "manualfeed")
    assert result["count"] == 2
    client = TestClient(main.app)
    source = next(x for x in client.get("/api/v1/sources").json() if x["id"] == "manualfeed")
    assert source["cntry_origin"] == "US"
    assert source["file_path"] == str(feed.resolve())
    assert client.get("/api/v1/data", params={"sources": "manualfeed"}).json()["total"] == 2
    feed.write_text("invalid\\n", encoding="utf-8")
    with pytest.raises(ValueError):
        refresh_source(db_path, "manualfeed")
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM records WHERE source_id='manualfeed'").fetchone()[0] == 2


def test_source_location_and_country_validation():
    valid = {"id": "example", "name": "Example", "format": "ip_text"}
    for fields in ({}, {"url": "https://example.com", "file_path": "local.txt"},
                   {"file_path": "local.txt", "cntry_origin": "China"},
                   {"file_path": ""}):
        with pytest.raises(ValueError):
            SourceDefinition(**valid, **fields)
    assert SourceDefinition(**valid, file_path="ips.txt", cntry_origin="CN").cntry_origin == "CN"


def test_existing_db_migrates_country_and_file_columns(tmp_path):
    db_path = tmp_path / "existing.db"
    init_db(db_path)
    with connect(db_path) as db:
        db.execute("UPDATE sources SET cntry_origin=NULL WHERE id='heybox'")
    init_db(db_path)
    with connect(db_path) as db:
        assert db.execute("SELECT cntry_origin FROM sources WHERE id='heybox'").fetchone()[0] == "CN"
        columns = {r["name"] for r in db.execute("PRAGMA table_info(sources)")}
        assert {"file_path", "cntry_origin"} <= columns
