from fastapi.testclient import TestClient
from app import main
from app.core import connect, init_db


def test_single_refresh_conflict_returns_409(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))

    def busy(*args, **kwargs):
        raise RuntimeError("Source refresh already in progress")

    monkeypatch.setattr(main, "refresh_source", busy)
    response = TestClient(main.app).post("/api/v1/sources/heybox/refresh")
    assert response.status_code == 409
    assert response.json()["detail"] == "Source refresh already in progress"


def test_refresh_all_distinguishes_skips_from_failures(tmp_path, monkeypatch):
    path = tmp_path / "service.db"
    init_db(path)
    monkeypatch.setattr(main, "DB_PATH", str(path))

    def refresh(*args, **kwargs):
        source_id = args[1]
        if source_id == "heybox":
            raise RuntimeError("Source refresh already in progress")
        return {"source": source_id, "count": 3}

    monkeypatch.setattr(main, "refresh_source", refresh)
    response = TestClient(main.app).post("/api/v1/sources/refresh-all")
    assert response.status_code == 200
    result = response.json()
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["skipped"] == 1
    assert {"source": "heybox", "success": False, "skipped": True,
            "reason": "already_in_progress"} in result["results"]
