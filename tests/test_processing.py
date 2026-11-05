import ipaddress
from app.core import init_db, connect
from app.processing import aggregate, page_networks, get_data


def test_collapse_overlaps_and_adjacent():
    blocks = aggregate(["192.0.2.0/25", "192.0.2.128/25", "192.0.2.1/32"])
    assert [str(n) for n in blocks] == ["192.0.2.0/24"]


def test_ipv4_ipv6_separate():
    blocks = aggregate(["2001:db8::/127", "192.0.2.1/32"])
    assert [str(n) for n in blocks] == ["192.0.2.1/32", "2001:db8::/127"]
    assert [str(n) for n in aggregate([str(n) for n in blocks], "ipv6")] == ["2001:db8::/127"]


def test_ip_page_without_expanding_entire_range():
    blocks = aggregate(["10.0.0.0/8"])
    items, total = page_networks(blocks, "ip", offset=16777214, limit=10)
    assert items == ["10.255.255.254", "10.255.255.255"]
    assert total == 16777216


def test_cross_source_dedup(tmp_path):
    path = tmp_path / "service.db"
    init_db(path)
    with connect(path) as db:
        db.execute("INSERT INTO records VALUES (?,?)", ("uubooster", "192.0.2.0/24"))
        db.execute("INSERT INTO records VALUES (?,?)", ("heybox", "192.0.2.1/32"))
    data = get_data(path)
    assert data["data"] == ["192.0.2.0/24"]
    assert data["total"] == 1
    assert get_data(path, ["heybox"], output_format="ip")["data"] == ["192.0.2.1"]


def test_network_and_broadcast_included():
    items, total = page_networks([ipaddress.ip_network("192.0.2.0/30")], "ip")
    assert total == 4
    assert items == ["192.0.2.0", "192.0.2.1", "192.0.2.2", "192.0.2.3"]
