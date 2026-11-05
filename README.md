# Booster IP Service

Local-first source ingestion service for booster IP/CIDR feeds. **Phase 1**: configuration, ingestion, snapshots, and source status. Aggregation and the web UI come in later phases.

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
- No combined deduplication/CIDR conversion API or web UI yet.
- SQLite stores the latest successful snapshot per source and refresh history.
