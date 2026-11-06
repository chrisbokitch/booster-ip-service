# Booster IP Service

Local-first service for collecting, normalizing, and combining IP address and CIDR feeds. It maintains per-source snapshots, aggregates overlapping or adjacent ranges, and provides a dashboard and paginated API for consuming the results.

## Windows / Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
npm run setup
npm test
npm run dev
```

Visit http://127.0.0.1:8000/ for the dashboard or http://127.0.0.1:8000/docs for the interactive API interface.

## Configuring sources

Source definitions are maintained in the version-controlled `sources.json` file. The application validates the file at startup and synchronizes source definitions into SQLite. Source configuration is not editable through the API or dashboard.

The `sources` array contains one object per feed. Each source supports:

| Attribute | Required | Description |
| --- | --- | --- |
| `id` | Yes | Unique, stable ID: lowercase letter followed by 1–63 lowercase letters, digits, underscores or hyphens |
| `name` | Yes | Display name, 1–100 characters |
| `url` | One of `url` / `file_path` | HTTPS URL for an automated upstream feed; credentials and redirects are not supported |
| `file_path` | One of `url` / `file_path` | Local file on the service host; relative paths resolve from the directory containing `sources.json` |
| `format` | Yes | `cidr_text`, `ip_text`, or `json` |
| `json_path` | For JSON feeds | Dot-separated path to an array of IP strings, e.g. `result.ips` |
| `cntry_origin` | No | Two-letter uppercase country code (e.g. `CN`); descriptive source metadata, not IP geolocation |
| `enabled` | No | Boolean; defaults to `true` |
| `refresh_interval_minutes` | No | `null` (default) disables automatic refresh; integer 1–10,080 enables it; `1440` means every 24 hours. **Zero is invalid.** |

### HTTPS source example

```json
{
  "id": "example_remote",
  "name": "Example Remote",
  "url": "https://example.com/networks.txt",
  "format": "cidr_text",
  "cntry_origin": "CN",
  "enabled": true,
  "refresh_interval_minutes": 1440
}
```

### Local file source example

For a booster that provides a list directly, save it as a UTF-8 text file on the application host, for example `feeds/manual-booster.txt`:

```text
2001:db8:10::/48
2001:db8:20::/48
192.0.2.0/24
```

Add the following object to the `sources` array in `sources.json`:

```json
{
  "id": "manual_booster",
  "name": "Manual Booster",
  "file_path": "feeds/manual-booster.txt",
  "format": "cidr_text",
  "cntry_origin": "CN",
  "enabled": true,
  "refresh_interval_minutes": null
}
```

The `cidr_text` format accepts one IP address or CIDR range per line, ignoring blank lines and lines beginning with `#`. Use `ip_text` for lists of individual addresses. The `json` format expects an array of IP addresses at the specified `json_path`. Local and HTTPS feeds use the same validation and normalization pipeline.

The local file must exist **on the service host**, and the service account needs permission to read it. A local file is ingested when manually refreshed from the dashboard or API, or when its configured automatic refresh becomes due. Changing the file on disk does not automatically trigger ingestion. Missing, empty, invalid, or oversized (over 10 MB) files fail the refresh without overwriting the previous successful snapshot.

### Applying changes

1. Add or edit entries in `sources.json` (or the path set by `BOOSTER_SOURCES_CONFIG`).
2. Deploy the configuration and any required local files.
3. Restart the service to load the definitions.
4. Manually refresh newly added sources to populate their snapshots immediately, if desired.

A changed source URL, local file path, format, or JSON path invalidates its cached snapshot. Renaming a source or updating its country metadata preserves the snapshot. Removing a source removes it and its active snapshot from SQLite; refresh history is retained. Invalid configuration prevents startup rather than silently skipping a source.

The current configuration includes **uuBooster** and **HEYBOX**, both with `cntry_origin: "CN"` and automatic refresh every 1,440 minutes (24 hours). The API exposes source status, history, data, and manual refresh operations, but no source creation, editing, or deletion endpoints.

## Security and scope

The development server binds to localhost and has no authentication. Deploy only behind EA's internal network restrictions and an HTTPS reverse proxy. Source URLs must be HTTPS and resolve to public addresses; redirects are disabled. Fetches have a timeout and a 10 MB response-size check (currently after download). Apply outbound egress restrictions and streaming download limits before exposing source configuration to untrusted operators.

## Data API

`GET /api/v1/data` combines the latest snapshots from all **enabled** sources by default. Use `sources=uubooster,heybox` to explicitly select sources (including disabled sources with existing snapshots). Source IDs are validated; unknown IDs return 404.

Examples:
- `/api/v1/data?format=cidr`
- `/api/v1/data?sources=uubooster,heybox&format=cidr&family=ipv4`
- `/api/v1/data?sources=heybox&format=ip&limit=1000&offset=0`

Output includes `data`, `total` (total records for the requested output format), `count` (returned page size), `sources`, and per-source refresh metadata. Results are sorted by IP version and numeric address, with overlapping/adjacent ranges collapsed. IP output includes all addresses in each range (including IPv4 network and broadcast addresses); pages are generated lazily rather than expanding entire networks. Maximum page size: 1,000,000. No snapshot means no records, not an automatic fetch.

## Data availability indicators

Both `GET /api/v1/sources` and the `source_status` entries in `GET /api/v1/data` include `data_status`:

- `pending`: no successful ingestion yet (even if a refresh attempt failed).
- `ready`: a successful snapshot exists and the latest refresh did not fail.
- `stale`: a successful snapshot exists, but a later refresh failed; cached records remain available.

`GET /api/v1/data` includes `complete`: `true` when **every selected source has a successful snapshot**, including stale snapshots; `false` when at least one selected source is pending. An empty source selection is vacuously complete. `complete` is an availability indicator, **not a freshness guarantee**. Check `data_status` and `last_success` for freshness. Source status is based on the latest recorded refresh result, not an elapsed-time threshold.

## Output formats and pagination

The `GET /api/v1/data` endpoint supports two representations using the `output` query parameter:

| Output | Content type | Intended use |
| --- | --- | --- |
| `output=json` (default) | `application/json` | Structured consumers and monitoring |
| `output=list` | `text/plain` | Scripts and tools expecting one CIDR/IP per line |

Both modes accept `sources`, `format=cidr|ip`, `family=all|ipv4|ipv6`, `offset`, and `limit`. Pagination is zero-based, default 1,000, maximum 1,000,000. JSON includes `has_more` and `next_offset`; list mode exposes `X-Total-Count`, `X-Result-Count`, `X-Data-Complete`, `X-Has-More`, and `X-Next-Offset` headers.

Examples:

```bash
curl 'http://127.0.0.1:8000/api/v1/data?output=list&format=cidr&limit=10000' -o booster-cidrs.txt
curl 'http://127.0.0.1:8000/api/v1/data?output=json&format=ip&family=ipv4&limit=1000&offset=0'
```

List output is newline-separated, with a trailing newline for nonempty pages. An empty result is an empty body. **List output is paginated, not an unbounded full download**; check the headers for more pages. 

Error responses: 404 for unknown source IDs; 422 for invalid query parameters or an empty explicit source selection. A source with no snapshot contributes no records, and `complete=false` signals missing source snapshots. A stale source still contributes its last successful snapshot. Neither output mode refreshes feeds. API documentation is available at `/docs` and the OpenAPI schema at `/openapi.json`.

**Deployment note:** Run behind internal network access controls and HTTPS termination; API requests are unauthenticated.

## Local dashboard

Open `http://127.0.0.1:8000/` after `npm run dev`. The dashboard uses plain HTML, CSS, and JavaScript, served directly by FastAPI with no frontend build step or extra dependencies. It shows source readiness, last successful refresh, record counts and errors; offers per-source manual refresh; and displays paginated combined CIDR or individual-IP output with address-family selection, copy-page, and download-page controls.

Copy and download apply **only to the displayed page**. A source refresh fetches the upstream feed and updates its stored snapshot; output is then reloaded. Disabled sources cannot be refreshed through the dashboard. The dashboard is intended for localhost use only: its refresh actions are unauthenticated, so do not expose the server to untrusted clients.

### Dashboard source and page controls

The combined output has checkboxes for individual enabled sources (all enabled sources selected initially), plus a **Select all enabled** shortcut. Unchecking every source shows an empty selection rather than silently querying all enabled sources. The page size is a custom integer between 1 and 1,000,000, validated before requesting data. Changing source selection, format, family, or page size returns to the first page. Disabled sources remain visible in source status but cannot be selected in the dashboard.

### Page size presets

The dashboard offers 1,000 (default), 10,000, and Custom buttons. Custom enables an integer field for 1–1,000,000 results. The same upper bound is enforced by the API to avoid unbounded memory and response sizes, especially when expanding CIDRs into individual IP addresses. Large pages may be slow and memory-intensive; pagination remains recommended.

## Automatic refresh and history

Set `refresh_interval_minutes` in `sources.json` to enable an automatic refresh interval (1, 6, 12 or 24 hours, or a custom interval of 1–10,080 minutes). Automatic refresh is **off by default**. Intervals are defined in JSON; next-run timestamps are persisted in SQLite; disabling a source pauses its schedule. When enabled or reconfigured, the first automatic refresh is scheduled one interval later. Manual refreshes also reset the next scheduled run. A lightweight application-lifecycle worker checks for due refreshes every 30 seconds, while a per-source SQLite lease prevents simultaneous manual/scheduled refreshes across workers sharing the database. Leases expire after 120 seconds to recover from crashed workers; ownership is verified before writing snapshots, so an expired worker cannot overwrite newer data. Keep SQLite on a local filesystem shared by workers on the same host; separate hosts require a shared coordination service.

The History button displays recent success/failure events, record counts and errors. API: `GET /api/v1/sources/{source_id}/history?limit=50` (limit 1–200). Failed fetches retain prior snapshots and advance the next scheduled run. The scheduler only runs while the application is running; after restart, overdue schedules are picked up on the next scan. Restrict access to the internal network.

## Refresh concurrency

Refresh attempts for the same source use an atomic SQLite lease, shared by all workers using the same database file. A concurrent single-source refresh returns HTTP 409; Refresh All reports that source as skipped. Leases expire after 120 seconds to recover from crashes, and lease ownership is checked before snapshot writes. The 120-second limit is a safety bound; exceptionally slow refreshes may lose their lease and fail rather than publish stale results. SQLite should remain on a local filesystem, not an unreliable network share. Multiple independent servers with separate databases are not coordinated.
