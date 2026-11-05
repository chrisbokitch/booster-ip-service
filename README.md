# Booster IP Service

Local-first source ingestion service for booster IP/CIDR feeds. **Phases 1–4**: configuration, ingestion, snapshots, normalization, cross-source aggregation, paginated IP/CIDR output, and a lightweight local dashboard.

## Windows / Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
npm run setup
npm test
npm run dev
```

Visit http://127.0.0.1:8000/ for the dashboard or http://127.0.0.1:8000/docs for the interactive API interface.

## Initial sources

- `uubooster`: CIDR text feed
- `heybox`: JSON feed, `result.ips`

Both sources are seeded automatically. **They are not fetched automatically** in Phase 1. To ingest data, open `/docs`, use `POST /api/v1/sources/{source_id}/refresh`, and supply `uubooster` or `heybox`. The latest successful snapshot remains available if a refresh fails. Use `GET /api/v1/sources` for status and `GET /api/v1/sources/{source_id}/records` for normalized records.

Use `POST /api/v1/sources` to register additional sources. Supported formats: `cidr_text`, `ip_text`, `json` (with a dot-separated `json_path`).

## Security and scope

This development server binds only to localhost and has **no authentication**. Do not expose it publicly or deploy it as-is. Admin endpoints, including source creation and refresh, require authentication before hosting. Sources are HTTPS-only, redirects are disabled, DNS must resolve exclusively to public IPs, and ingestion rejects empty/invalid feeds. Configured URLs should be treated as trusted administrator input; additional network egress controls and DNS-rebinding protections are recommended before deployment.

## Phase 1 limitations

- No scheduled refresh yet; manual refresh only.
- No source edit/delete endpoints yet.
- Dashboard is local-only; no authentication or public deployment support yet.
- SQLite stores the latest successful snapshot per source and refresh history.

## Phase 2 data API

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

## Phase 3: consumption and pagination

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

List output is newline-separated, with a trailing newline for nonempty pages. An empty result is an empty body. **List output is paginated, not an unbounded full download**; check the headers for more pages. The former `/api/v1/data.txt` endpoint has been removed.

Error responses: 404 for unknown source IDs; 422 for invalid query parameters or an empty explicit source selection. A source with no snapshot contributes no records, and `complete=false` signals missing source snapshots. A stale source still contributes its last successful snapshot. Neither output mode refreshes feeds. API documentation is available at `/docs` and the OpenAPI schema at `/openapi.json`.

**Deployment note:** This is a local-only unauthenticated development API. Do not expose it publicly until access policy and authentication are decided.

## Phase 4: local dashboard

Open `http://127.0.0.1:8000/` after `npm run dev`. The dashboard uses plain HTML, CSS, and JavaScript, served directly by FastAPI with no frontend build step or extra dependencies. It shows source readiness, last successful refresh, record counts and errors; offers per-source manual refresh; and displays paginated combined CIDR or individual-IP output with address-family selection, copy-page, and download-page controls.

Copy and download apply **only to the displayed page**. A source refresh fetches the upstream feed and updates its stored snapshot; output is then reloaded. Disabled sources cannot be refreshed through the dashboard. The dashboard is intended for localhost use only: its refresh actions are unauthenticated, so do not expose the server to untrusted clients.

### Dashboard source and page controls

The combined output has checkboxes for individual enabled sources (all enabled sources selected initially), plus a **Select all enabled** shortcut. Unchecking every source shows an empty selection rather than silently querying all enabled sources. The page size is a custom integer between 1 and 1,000,000, validated before requesting data. Changing source selection, format, family, or page size returns to the first page. Disabled sources remain visible in source status but cannot be selected in the dashboard.

### Page size presets

The dashboard offers 1,000 (default), 10,000, and Custom buttons. Custom enables an integer field for 1–1,000,000 results. The same upper bound is enforced by the API to avoid unbounded memory and response sizes, especially when expanding CIDRs into individual IP addresses. Large pages may be slow and memory-intensive; pagination remains recommended.

## Phase 5: manual source management

The local dashboard now supports adding sources, editing name/URL/format/JSON path/enabled status, removing sources, and refreshing all enabled sources. Source IDs are immutable after creation. Editing the feed URL, format, or JSON path **clears the old snapshot** to prevent publishing data associated with an outdated feed definition; refresh the source to populate it again. Changing name or enabled status preserves its snapshot. Deletion removes the source, its snapshot, and its refresh history. Deleted built-in sources are not silently re-created on restart; a source with the same ID can be manually added later.

`PUT /api/v1/sources/{source_id}` updates a source, `DELETE /api/v1/sources/{source_id}` removes it, and `POST /api/v1/sources/refresh-all` refreshes each enabled source independently, returning per-source success/failure and totals. Automatic scheduling and refresh-history UI remain future work.

**Security:** These management endpoints are unauthenticated and must remain localhost-only. Do not expose the service on the public internet.

## Phase 5.2: automatic refresh and history

Edit a source to enable an automatic refresh interval (1, 6, 12 or 24 hours, or a custom interval of 1–10,080 minutes). Automatic refresh is **off by default**. Intervals and next-run timestamps are persisted in SQLite; disabling a source pauses its schedule. When enabled or reconfigured, the first automatic refresh is scheduled one interval later. Manual refreshes also reset the next scheduled run. A lightweight application-lifecycle worker checks for due refreshes every 30 seconds, while a per-source in-process lock prevents simultaneous manual/scheduled refreshes. Run the app with a single worker process; cross-process scheduling coordination is not implemented.

The History button displays recent success/failure events, record counts and errors. API: `GET /api/v1/sources/{source_id}/history?limit=50` (limit 1–200). Failed fetches retain prior snapshots and advance the next scheduled run. The scheduler only runs while the application is running; after restart, overdue schedules are picked up on the next scan. Avoid exposing the unauthenticated service beyond localhost.
