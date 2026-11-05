"""Source ingestion, validation, and persistent snapshots."""
import ipaddress
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx

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
        CREATE TABLE IF NOT EXISTS refresh_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
          at TEXT NOT NULL, success INTEGER NOT NULL, count INTEGER, error TEXT
        );
        """)
        for source in DEFAULT_SOURCES:
            db.execute("INSERT OR IGNORE INTO sources(id,name,url,format,json_path) VALUES (?,?,?,?,?)", source)


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


def refresh_source(path, source_id, *, client=None):
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
            db.execute("DELETE FROM records WHERE source_id=?", (source_id,))
            db.executemany("INSERT INTO records(source_id,network) VALUES (?,?)", [(source_id,n) for n in networks])
            db.execute("UPDATE sources SET last_success=?, last_error=NULL WHERE id=?", (now,source_id))
            db.execute("INSERT INTO refresh_history(source_id,at,success,count) VALUES (?,?,1,?)", (source_id,now,len(networks)))
            return {"source":source_id,"count":len(networks),"refreshed_at":now}
        except Exception as exc:
            db.execute("UPDATE sources SET last_error=? WHERE id=?", (str(exc),source_id))
            db.execute("INSERT INTO refresh_history(source_id,at,success,error) VALUES (?,?,0,?)", (source_id,now,str(exc)))
            raise
