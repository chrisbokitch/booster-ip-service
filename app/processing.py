"""Canonical IP range aggregation and bounded output conversion."""
import ipaddress
from .core import connect

MAX_IP_PAGE = 10000


def aggregate(networks, family="all"):
    if family not in ("all", "ipv4", "ipv6"):
        raise ValueError("Invalid address family")
    parsed = [ipaddress.ip_network(n, strict=False) for n in networks]
    if family != "all":
        version = 4 if family == "ipv4" else 6
        parsed = [n for n in parsed if n.version == version]
    result = []
    for version in (4, 6):
        result.extend(ipaddress.collapse_addresses(n for n in parsed if n.version == version))
    return list(result)


def page_networks(networks, output_format="cidr", offset=0, limit=1000):
    if output_format not in ("cidr", "ip"):
        raise ValueError("Invalid output format")
    if offset < 0 or limit < 1 or limit > MAX_IP_PAGE:
        raise ValueError("Invalid pagination")
    if output_format == "cidr":
        items = [str(n) for n in networks]
        return items[offset:offset + limit], len(items)
    total = sum(n.num_addresses for n in networks)
    result = []
    skip = offset
    for network in networks:
        size = network.num_addresses
        if skip >= size:
            skip -= size
            continue
        start = int(network.network_address) + skip
        count = min(limit - len(result), size - skip)
        address_type = ipaddress.IPv4Address if network.version == 4 else ipaddress.IPv6Address
        result.extend(str(address_type(start + i)) for i in range(count))
        skip = 0
        if len(result) >= limit:
            break
    return result, total


def get_data(path, selected=None, family="all", output_format="cidr", offset=0, limit=1000):
    with connect(path) as db:
        available = {row["id"]: dict(row) for row in db.execute("SELECT * FROM sources")}
        if selected is None:
            ids = sorted(key for key, source in available.items() if source["enabled"])
        else:
            ids = sorted(set(selected))
            unknown = set(ids) - set(available)
            if unknown:
                raise KeyError(", ".join(sorted(unknown)))
        if not ids:
            return {"sources": [], "format": output_format, "family": family,
                    "count": 0, "total": 0, "offset": offset, "limit": limit,
                    "data": [], "source_status": {}}
        placeholders = ",".join("?" for _ in ids)
        records = [row["network"] for row in db.execute(
            f"SELECT network FROM records WHERE source_id IN ({placeholders})", ids)]
        status = {key: {"last_success": available[key]["last_success"],
                        "last_error": available[key]["last_error"],
                        "enabled": bool(available[key]["enabled"])} for key in ids}
    networks = aggregate(records, family)
    items, total = page_networks(networks, output_format, offset, limit)
    return {"sources": ids, "format": output_format, "family": family,
            "count": len(items), "total": total, "offset": offset,
            "limit": limit, "data": items, "source_status": status}
