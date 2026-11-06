"""Source ingestion, validation, and persistent snapshots."""
import ipaddress
import json
import sqlite3
import threading
import uuid
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx

_refresh_locks = {}
_refresh_locks_guard = threading.Lock()

DEFAULT_SOURCES = [
    ("uubooster", "uuBooster", "https://uu-ovproxylist.easebar.com:8889/acc_exitip_ov_cidr_aggregated.txt", "cidr_text", None),
    ("heybox", "HEYBOX", "https://api.xiaoheihe.cn/heyboxaccip", "json", "result.ips"),
]


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
          format TEXT NOT NULL CHECK(format IN ('cidr_text','ip_text','json')),
          json_path TEXT, enabled INTEGER NOT NULL DEFAULT 1,
          last_success TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS records (
          source_id TEXT NOT NULL REFERENCES sources(id), network TEXT NOT NULL,
          PRIMARY KEY(source_id,network)
        );
        CREATE TABLE IF NOT EXISTS refresh_leases (
          source_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS refresh_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
          at TEXT NOT NULL, success INTEGER NOT NULL, count INTEGER, error TEXT
        );
        """)
        history_columns = {row["name"] for row in db.execute("PRAGMA table_info(refresh_history)")}
        if "trigger" not in history_columns:
            db.execute("ALTER TABLE refresh_history ADD COLUMN trigger TEXT")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(sources)")}
        if "refresh_interval_minutes" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN refresh_interval_minutes INTEGER")
        if "next_refresh" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN next_refresh TEXT")
        db.execute("CREATE TABLE IF NOT EXISTS deleted_sources (id TEXT PRIMARY KEY)")
        for source in DEFAULT_SOURCES:
            db.execute("INSERT OR IGNORE INTO sources(id,name,url,format,json_path) SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM deleted_sources WHERE id=?)", (*source, source[0]))


def parse_feed(raw, fmt, json_path=None):
    if fmt == "json":
        data = json.loads(raw)
        if not json_path:
            raise ValueError("JSON sources require json_path")
        for key in json_path.split('.'):
            if not isinstance(data, dict) or key not in data:
                raise ValueError(f"Missing JSON key: {key}")
            data = data[key]
        if not isinstance(data, list):
            raise ValueError("JSON path must resolve to an array")
        items = data
    elif fmt in ("cidr_text", "ip_text"):
        items = [line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    else:
        raise ValueError("Unsupported format")
    if not items:
        raise ValueError("Feed is empty; keeping previous snapshot")
    networks = set()
    for index, item in enumerate(items, 1):
        try:
            if not isinstance(item, str):
                raise ValueError("not a string")
            if fmt == "ip_text" or fmt == "json":
                network = ipaddress.ip_network(f"{ipaddress.ip_address(item)}/{32 if ':' not in item else 128}")
            else:
                network = ipaddress.ip_network(item, strict=False)
            networks.add(str(network))
        except ValueError as exc:
            raise ValueError(f"Invalid entry at position {index}: {item!r}: {exc}") from exc
    return sorted(networks, key=lambda n: (ipaddress.ip_network(n).version, int(ipaddress.ip_network(n).network_address), ipaddress.ip_network(n).prefixlen))


def _refresh_source(path, source_id, *, client=None, trigger="manual", owner=None):
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        if not row['enabled']:
            raise ValueError("Source is disabled")
        try:
            parts = urlsplit(row['url'])
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                raise ValueError("Source URL must be HTTPS without credentials")
            import socket
            addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError("Source host must resolve exclusively to public IP addresses")
            if client is None:
                with httpx.Client(timeout=20, follow_redirects=False) as session:
                    response = session.get(row['url'])
            else:
                response = client.get(row['url'])
            response.raise_for_status()
            if len(response.content) > 10_000_000:
                raise ValueError("Feed exceeds 10 MB")
            networks = parse_feed(response.text, row['format'], row['json_path'])
            if owner is not None:
                _verify_lease(db, source_id, owner)
            db.execute("DELETE FROM records WHERE source_id=?", (source_id,))
            db.executemany("INSERT INTO records(source_id,network) VALUES (?,?)", [(source_id,n) for n in networks])
            db.execute("UPDATE sources SET last_success=?, last_error=NULL WHERE id=?", (now,source_id))
            db.execute("INSERT INTO refresh_history(source_id,at,success,count,trigger) VALUES (?,?,1,?,?)", (source_id,now,len(networks),trigger))
            _advance_schedule(db, source_id, now)
            return {"source":source_id,"count":len(networks),"refreshed_at":now}
        except Exception as exc:
            if owner is not None:
                _verify_lease(db, source_id, owner)
            db.execute("UPDATE sources SET last_error=? WHERE id=?", (str(exc),source_id))
            db.execute("INSERT INTO refresh_history(source_id,at,success,error,trigger) VALUES (?,?,0,?,?)", (source_id,now,str(exc),trigger))
            _advance_schedule(db, source_id, now)
            db.commit()
            raise

def _advance_schedule(db, source_id, at):
    row = db.execute("SELECT enabled, refresh_interval_minutes FROM sources WHERE id=?", (source_id,)).fetchone()
    if row is None:
        return
    interval = row["refresh_interval_minutes"] if row["enabled"] else None
    next_at = (datetime.fromisoformat(at) + timedelta(minutes=interval)).isoformat() if interval else None
    db.execute("UPDATE sources SET next_refresh=? WHERE id=?", (next_at, source_id))


LEASE_SECONDS = 120


def _claim_lease(path, source_id, owner):
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
    with connect(path) as db:
        # SQLite serializes the claim, including claims from other processes.
        cursor = db.execute(
            "INSERT INTO refresh_leases(source_id,owner,expires_at) VALUES (?,?,?) "
            "ON CONFLICT(source_id) DO UPDATE SET owner=excluded.owner, "
            "expires_at=excluded.expires_at WHERE refresh_leases.expires_at<=?",
            (source_id, owner, expiry, now.isoformat()),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Source refresh already in progress")


def _verify_lease(db, source_id, owner):
    row = db.execute(
        "SELECT owner,expires_at FROM refresh_leases WHERE source_id=?", (source_id,)
    ).fetchone()
    if row is None or row["owner"] != owner or row["expires_at"] <= datetime.now(timezone.utc).isoformat():
        raise RuntimeError("Refresh lease expired or ownership changed")


def _release_lease(path, source_id, owner):
    with connect(path) as db:
        db.execute("DELETE FROM refresh_leases WHERE source_id=? AND owner=?", (source_id, owner))


def refresh_source(path, source_id, *, client=None, trigger="manual"):
    if trigger not in ("manual", "scheduled"):
        raise ValueError("Invalid refresh trigger")
    with _refresh_locks_guard:
        lock = _refresh_locks.setdefault((str(path), source_id), threading.Lock())
    if not lock.acquire(blocking=False):
        raise RuntimeError("Source refresh already in progress")
    owner = uuid.uuid4().hex
    claimed = False
    try:
        _claim_lease(path, source_id, owner)
        claimed = True
        return _refresh_source(path, source_id, client=client, trigger=trigger, owner=owner)
    finally:
        try:
            if claimed:
                _release_lease(path, source_id, owner)
        finally:
            lock.release()


def refresh_due_sources(path, now=None):
    now = now or datetime.now(timezone.utc)
    with connect(path) as db:
        ids = [row["id"] for row in db.execute(
            "SELECT id FROM sources WHERE enabled=1 AND refresh_interval_minutes IS NOT NULL "
            "AND next_refresh IS NOT NULL AND next_refresh<=? ORDER BY next_refresh",
            (now.isoformat(),))]
    for source_id in ids:
        try:
            refresh_source(path, source_id, trigger="scheduled")
        except Exception:
            # Failures are recorded by refresh_source; concurrent manual refresh owns the schedule.
            pass
