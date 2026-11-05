import os
import re
import threading
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlite3 import IntegrityError
from .core import connect, init_db, refresh_source, refresh_due_sources
from .processing import source_data_status

DB_PATH = os.environ.get('BOOSTER_DB', 'data/booster.sqlite3')

@asynccontextmanager
async def lifespan(app):
    init_db(DB_PATH)
    stop = threading.Event()
    def scheduler():
        while not stop.wait(30):
            try:
                refresh_due_sources(DB_PATH)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Scheduled refresh scan failed")
    worker = threading.Thread(target=scheduler, name="booster-refresh", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=2)

app = FastAPI(title='Booster IP Service', version='0.1.0', lifespan=lifespan)

class SourceConfig(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    format: str
    json_path: str | None = None
    enabled: bool = True
    refresh_interval_minutes: int | None = Field(default=None, ge=1, le=10080)

class SourceInput(SourceConfig):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{1,63}$')
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    format: str
    json_path: str | None = None
    enabled: bool = True

def validate_source(source):
    if source.format not in ('cidr_text', 'ip_text', 'json'):
        raise HTTPException(422, 'Invalid source format')
    if source.format == 'json' and not source.json_path:
        raise HTTPException(422, 'JSON source requires json_path')
    if source.json_path and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*', source.json_path):
        raise HTTPException(422, 'Invalid JSON path')
    if source.url.scheme != 'https' or source.url.username or source.url.password:
        raise HTTPException(422, 'HTTPS without credentials is required')


def schedule_next(enabled, minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat() if enabled and minutes else None


@app.get('/api/v1/health')
def health():
    return {'status':'ok'}

@app.get('/api/v1/sources')
def sources():
    with connect(DB_PATH) as db:
        return [{**dict(row), 'data_status': source_data_status(row)} for row in db.execute('SELECT s.*, (SELECT COUNT(*) FROM records r WHERE r.source_id=s.id) AS record_count FROM sources s ORDER BY id')]

@app.post('/api/v1/sources', status_code=201)
def create_source(source: SourceInput):
    validate_source(source)
    with connect(DB_PATH) as db:
        try:
            db.execute('INSERT INTO sources(id,name,url,format,json_path,enabled,refresh_interval_minutes,next_refresh) VALUES (?,?,?,?,?,?,?,?)',
                       (source.id,source.name,str(source.url),source.format,source.json_path,int(source.enabled),
                        source.refresh_interval_minutes, schedule_next(source.enabled, source.refresh_interval_minutes)))
        except IntegrityError:
            raise HTTPException(409,'Source ID already exists')
    return {'id':source.id}

@app.put('/api/v1/sources/{source_id}')
def update_source(source_id: str, source: SourceConfig):
    validate_source(source)
    with connect(DB_PATH) as db:
        previous = db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
        if previous is None:
            raise HTTPException(404, 'Unknown source')
        changed = (previous['url'] != str(source.url) or previous['format'] != source.format
                   or previous['json_path'] != source.json_path)
        db.execute('UPDATE sources SET name=?,url=?,format=?,json_path=?,enabled=?,'
                   'last_success=CASE WHEN ? THEN NULL ELSE last_success END,'
                   'last_error=CASE WHEN ? THEN NULL ELSE last_error END,'
                   'refresh_interval_minutes=?,next_refresh=? WHERE id=?',
                   (source.name, str(source.url), source.format, source.json_path,
                    int(source.enabled), changed, changed, source.refresh_interval_minutes,
                    (previous['next_refresh'] if previous['enabled'] and source.enabled
                     and previous['refresh_interval_minutes'] == source.refresh_interval_minutes and not changed
                     else schedule_next(source.enabled, source.refresh_interval_minutes)), source_id))
        if changed:
            db.execute('DELETE FROM records WHERE source_id=?', (source_id,))
    return {'id': source_id, 'snapshot_cleared': changed}


@app.delete('/api/v1/sources/{source_id}', status_code=204)
def delete_source(source_id: str):
    with connect(DB_PATH) as db:
        if not db.execute('SELECT 1 FROM sources WHERE id=?', (source_id,)).fetchone():
            raise HTTPException(404, 'Unknown source')
        db.execute('INSERT OR IGNORE INTO deleted_sources(id) VALUES (?)', (source_id,))
        db.execute('DELETE FROM refresh_history WHERE source_id=?', (source_id,))
        db.execute('DELETE FROM records WHERE source_id=?', (source_id,))
        db.execute('DELETE FROM sources WHERE id=?', (source_id,))


@app.get('/api/v1/sources/{source_id}/history')
def source_history(source_id: str, limit: int = 50):
    if not 1 <= limit <= 200:
        raise HTTPException(422, 'History limit must be between 1 and 200')
    with connect(DB_PATH) as db:
        if not db.execute('SELECT 1 FROM sources WHERE id=?', (source_id,)).fetchone():
            raise HTTPException(404, 'Unknown source')
        return [dict(row) for row in db.execute(
            'SELECT at,success,count,error FROM refresh_history WHERE source_id=? ORDER BY id DESC LIMIT ?',
            (source_id, limit))]


@app.post('/api/v1/sources/refresh-all')
def refresh_all_sources():
    with connect(DB_PATH) as db:
        ids = [row['id'] for row in db.execute('SELECT id FROM sources WHERE enabled=1 ORDER BY id')]
    results = []
    for source_id in ids:
        try:
            result = refresh_source(DB_PATH, source_id)
            results.append({'source': source_id, 'success': True, 'count': result['count']})
        except Exception as exc:
            results.append({'source': source_id, 'success': False, 'error': str(exc)})
    return {'results': results, 'succeeded': sum(item['success'] for item in results),
            'failed': sum(not item['success'] for item in results)}


@app.post('/api/v1/sources/{source_id}/refresh')
def refresh(source_id: str):
    try:
        return refresh_source(DB_PATH,source_id)
    except KeyError:
        raise HTTPException(404,'Unknown source')
    except Exception as exc:
        raise HTTPException(502,f'Refresh failed: {exc}')

@app.get('/api/v1/sources/{source_id}/records')
def records(source_id: str):
    with connect(DB_PATH) as db:
        if not db.execute('SELECT 1 FROM sources WHERE id=?',(source_id,)).fetchone():
            raise HTTPException(404,'Unknown source')
        return {'source':source_id,'networks':[r['network'] for r in db.execute('SELECT network FROM records WHERE source_id=? ORDER BY network',(source_id,))]}

from typing import Literal
from fastapi import Query
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .processing import get_data

@app.get('/api/v1/data')
def data(
    sources: str | None = Query(default=None, description="Comma-separated source IDs; omit for all enabled sources"),
    format: Literal['cidr', 'ip'] = 'cidr',
    family: Literal['all', 'ipv4', 'ipv6'] = 'all',
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=1000000),
):
    selected = None if sources is None else [s.strip() for s in sources.split(',') if s.strip()]
    if sources is not None and not selected:
        raise HTTPException(422, 'Specify at least one source')
    try:
        return get_data(DB_PATH, selected, family, format, offset, limit)
    except KeyError as exc:
        raise HTTPException(404, f'Unknown source: {exc}')

@app.get(
    '/api/v1/data.txt',
    response_class=PlainTextResponse,
    summary='Export normalized addresses as newline-separated text',
    description='Returns a bounded page of CIDRs or individual IPs, one per line. '
                'Uses stored snapshots; never triggers a source refresh.',
)
def data_text(
    sources: str | None = Query(default=None, description="Comma-separated source IDs; omit for all enabled sources"),
    format: Literal['cidr', 'ip'] = 'cidr',
    family: Literal['all', 'ipv4', 'ipv6'] = 'all',
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=1000000),
):
    result = data(sources=sources, format=format, family=family, offset=offset, limit=limit)
    body = "\n".join(result['data'])
    if body:
        body += "\n"
    return PlainTextResponse(
        body,
        headers={
            'X-Total-Count': str(result['total']),
            'X-Result-Count': str(result['count']),
            'X-Data-Complete': str(result['complete']).lower(),
            'X-Has-More': str(result['has_more']).lower(),
            'X-Next-Offset': str(result['next_offset']) if result['next_offset'] is not None else '',
        },
    )

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")
