import pytest
from app import core


def test_refresh_lease_rejects_second_owner_and_recovers_expiry(tmp_path):
    path = tmp_path / "leases.db"
    core.init_db(path)
    core._claim_lease(path, "heybox", "first")
    with pytest.raises(RuntimeError, match="already in progress"):
        core._claim_lease(path, "heybox", "second")
    with core.connect(path) as db:
        db.execute("UPDATE refresh_leases SET expires_at=? WHERE source_id=?",
                   ("2000-01-01T00:00:00+00:00", "heybox"))
    core._claim_lease(path, "heybox", "second")
    with core.connect(path) as db:
        with pytest.raises(RuntimeError, match="ownership changed"):
            core._verify_lease(db, "heybox", "first")
    core._release_lease(path, "heybox", "first")
    with core.connect(path) as db:
        assert db.execute("SELECT owner FROM refresh_leases WHERE source_id='heybox'").fetchone()["owner"] == "second"
    core._release_lease(path, "heybox", "second")


def test_refresh_lease_blocks_other_process_connections(tmp_path):
    path = tmp_path / "leases.db"
    core.init_db(path)
    core._claim_lease(path, "heybox", "first")
    with pytest.raises(RuntimeError, match="already in progress"):
        core._claim_lease(path, "heybox", "second")
    core._release_lease(path, "heybox", "first")
    core._claim_lease(path, "heybox", "second")
    core._release_lease(path, "heybox", "second")
