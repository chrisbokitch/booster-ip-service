import json
import pytest
from app.core import init_db, connect, parse_feed


def test_cidr_text():
    assert parse_feed('192.0.2.0/24\n192.0.2.0/24\n', 'cidr_text') == ['192.0.2.0/24']


def test_heybox_json():
    raw = json.dumps({'result': {'ips': ['192.0.2.1', '192.0.2.1', '2001:db8::1']}})
    assert parse_feed(raw, 'json', 'result.ips') == ['192.0.2.1/32', '2001:db8::1/128']


def test_invalid_feed():
    with pytest.raises(ValueError):
        parse_feed('not an IP', 'ip_text')


def test_empty_feed_rejected():
    with pytest.raises(ValueError):
        parse_feed('', 'cidr_text')


def test_defaults_idempotent(tmp_path):
    path = tmp_path / 'test.db'
    init_db(path)
    init_db(path)
    with connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == 3


def test_source_config_rejects_invalid_and_duplicate_entries(tmp_path):
    from app.config import load_source_config
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [
        {"id": "sample", "name": "Sample", "url": "http://example.com/feed", "format": "cidr_text"}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_source_config(path)
    entry = {"id": "sample", "name": "Sample", "url": "https://example.com/feed", "format": "cidr_text"}
    path.write_text(json.dumps({"sources": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate source IDs"):
        load_source_config(path)
    path.write_text(json.dumps({"sources": [{**entry, "format": "invalid"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_source_config(path)
