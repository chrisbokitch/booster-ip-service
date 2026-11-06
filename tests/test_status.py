from app.core import connect, init_db
from app.processing import get_data, source_data_status


def test_status_transitions():
    assert source_data_status({"last_success": None, "last_error": None}) == "pending"
    assert source_data_status({"last_success": None, "last_error": "failure"}) == "pending"
    assert source_data_status({"last_success": "2026-11-05", "last_error": None}) == "ready"
    assert source_data_status({"last_success": "2026-11-05", "last_error": "timeout"}) == "stale"


def test_completeness_tracks_snapshots_not_errors(tmp_path):
    path = tmp_path / "service.db"
    init_db(path)
    assert get_data(path)["complete"] is False
    assert get_data(path)["source_status"]["uubooster"]["data_status"] == "pending"
    with connect(path) as db:
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='heybox'")
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='local_example'")
        db.execute("UPDATE sources SET last_success='2026-11-05', last_error='timeout' WHERE id='uubooster'")
    result = get_data(path)
    assert result["complete"] is True
    assert result["source_status"]["uubooster"]["data_status"] == "stale"
    assert result["source_status"]["heybox"]["data_status"] == "ready"
    assert result["source_status"]["local_example"]["data_status"] == "ready"


def test_explicit_subset_completeness(tmp_path):
    path = tmp_path / "service.db"
    init_db(path)
    with connect(path) as db:
        db.execute("UPDATE sources SET last_success='2026-11-05' WHERE id='heybox'")
    assert get_data(path, selected=["heybox"])["complete"] is True
    assert get_data(path, selected=["uubooster"])["complete"] is False
    assert get_data(path, selected=[])["complete"] is True
