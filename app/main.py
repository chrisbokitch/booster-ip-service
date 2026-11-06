import os
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from typing import Literal
from .core import connect, init_db, refresh_source, refresh_due_sources
from .processing import source_data_status, aggregate

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

@app.get('/api/v1/health')
def health():
    return {'status':'ok'}

@app.get('/api/v1/sources')
def sources():
    with connect(DB_PATH) as db:
        rows = db.execute('SELECT s.*, (SELECT COUNT(*) FROM records r WHERE r.source_id=s.id) AS record_count FROM sources s ORDER BY id').fetchall()
        result = []
        for row in rows:
            networks = [item['network'] for item in db.execute('SELECT network FROM records WHERE source_id=?', (row['id'],))]
            result.append({**dict(row), 'data_status': source_data_status(row),
                           'cidr_count': len(aggregate(networks))})
        return result

@app.get('/api/v1/sources/{source_id}/history')
def source_history(source_id: str, limit: int = 50):
    if not 1 <= limit <= 200:
        raise HTTPException(422, 'History limit must be between 1 and 200')
    with connect(DB_PATH) as db:
        if not db.execute('SELECT 1 FROM sources WHERE id=?', (source_id,)).fetchone():
            raise HTTPException(404, 'Unknown source')
        return [dict(row) for row in db.execute(
            'SELECT at,success,count,error,trigger FROM refresh_history WHERE source_id=? ORDER BY id DESC LIMIT ?',
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
        except RuntimeError as exc:
            if str(exc) == 'Source refresh already in progress':
                results.append({'source': source_id, 'success': False, 'skipped': True,
                                'reason': 'already_in_progress'})
            else:
                results.append({'source': source_id, 'success': False, 'error': str(exc)})
        except Exception as exc:
            results.append({'source': source_id, 'success': False, 'error': str(exc)})
    return {'results': results, 'succeeded': sum(item['success'] for item in results),
            'failed': sum(not item['success'] and not item.get('skipped') for item in results),
            'skipped': sum(item.get('skipped', False) for item in results)}


@app.post('/api/v1/sources/{source_id}/refresh')
def refresh(source_id: str):
    try:
        return refresh_source(DB_PATH,source_id)
    except KeyError:
        raise HTTPException(404,'Unknown source')
    except RuntimeError as exc:
        if str(exc) == 'Source refresh already in progress':
            raise HTTPException(409, str(exc)) from exc
        raise HTTPException(502, f'Refresh failed: {exc}') from exc
    except Exception as exc:
        raise HTTPException(502,f'Refresh failed: {exc}')

from fastapi import Query
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .processing import get_data

@app.get(
    '/api/v1/data',
    responses={200: {'content': {'application/json': {}, 'text/plain': {}}}},
)
def data(
    sources: str | None = Query(default=None, description="Comma-separated source IDs; omit for all enabled sources"),
    format: Literal['cidr', 'ip'] = 'cidr',
    family: Literal['all', 'ipv4', 'ipv6'] = 'all',
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=1000000),
    output: Literal['json', 'list'] = 'json',
):
    selected = None if sources is None else [s.strip() for s in sources.split(',') if s.strip()]
    if sources is not None and not selected:
        raise HTTPException(422, 'Specify at least one source')
    try:
        result = get_data(DB_PATH, selected, family, format, offset, limit)
    except KeyError as exc:
        raise HTTPException(404, f'Unknown source: {exc}')
    if output == 'json':
        return result
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
