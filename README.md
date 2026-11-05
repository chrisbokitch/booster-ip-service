# Booster IP Service

Local-first source ingestion service for booster IP/CIDR feeds. **Phases 1–2**: configuration, ingestion, snapshots, normalization, cross-source aggregation, and paginated IP/CIDR output. The web UI comes later.

## Windows / Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
npm run setup
npm test
npm run dev
```

Visit http://127.0.0.1:8000/docs for the interactive API interface.

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
- No web UI yet.
- SQLite stores the latest successful snapshot per source and refresh history.

## Phase 2 data API

`GET /api/v1/data` combines the latest snapshots from all **enabled** sources by default. Use `sources=uubooster,heybox` to explicitly select sources (including disabled sources with existing snapshots). Source IDs are validated; unknown IDs return 404.

Examples:
- `/api/v1/data?format=cidr`
- `/api/v1/data?sources=uubooster,heybox&format=cidr&family=ipv4`
- `/api/v1/data?sources=heybox&format=ip&limit=1000&offset=0`

Output includes `data`, `total` (total records for the requested output format), `count` (returned page size), `sources`, and per-source refresh metadata. Results are sorted by IP version and numeric address, with overlapping/adjacent ranges collapsed. IP output includes all addresses in each range (including IPv4 network and broadcast addresses); pages are generated lazily rather than expanding entire networks. Maximum page size: 10,000. No snapshot means no records, not an automatic fetch.
