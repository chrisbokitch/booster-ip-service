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
        assert db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == 2
