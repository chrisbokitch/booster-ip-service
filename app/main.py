import os
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from .core import connect, init_db, refresh_source
from .processing import source_data_status

DB_PATH = os.environ.get('BOOSTER_DB', 'data/booster.sqlite3')

@asynccontextmanager
async def lifespan(app):
    init_db(DB_PATH)
    yield

app = FastAPI(title='Booster IP Service', version='0.1.0', lifespan=lifespan)

class SourceInput(BaseModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{1,63}$')
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    format: str
    json_path: str | None = None
    enabled: bool = True

@app.get('/api/v1/health')
def health():
    return {'status':'ok'}

@app.get('/api/v1/sources')
def sources():
    with connect(DB_PATH) as db:
        return [{**dict(row), 'data_status': source_data_status(row)} for row in db.execute('SELECT s.*, (SELECT COUNT(*) FROM records r WHERE r.source_id=s.id) AS record_count FROM sources s ORDER BY id')]

@app.post('/api/v1/sources', status_code=201)
def create_source(source: SourceInput):
    if source.format not in ('cidr_text','ip_text','json'):
        raise HTTPException(422, 'Invalid source format')
    if source.format == 'json' and not source.json_path:
        raise HTTPException(422, 'JSON source requires json_path')
    if source.json_path and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*', source.json_path):
        raise HTTPException(422, 'Invalid JSON path')
    if source.url.scheme != 'https':
        raise HTTPException(422, 'HTTPS is required')
    with connect(DB_PATH) as db:
        try:
            db.execute('INSERT INTO sources(id,name,url,format,json_path,enabled) VALUES (?,?,?,?,?,?)', (source.id,source.name,str(source.url),source.format,source.json_path,int(source.enabled)))
        except __import__('sqlite3').IntegrityError:
            raise HTTPException(409,'Source ID already exists')
    return {'id':source.id}

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
from .processing import get_data

@app.get('/api/v1/data')
def data(
    sources: str | None = Query(default=None, description="Comma-separated source IDs; omit for all enabled sources"),
    format: Literal['cidr', 'ip'] = 'cidr',
    family: Literal['all', 'ipv4', 'ipv6'] = 'all',
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=10000),
):
    selected = None if sources is None else [s.strip() for s in sources.split(',') if s.strip()]
    if sources is not None and not selected:
        raise HTTPException(422, 'Specify at least one source')
    try:
        return get_data(DB_PATH, selected, family, format, offset, limit)
    except KeyError as exc:
        raise HTTPException(404, f'Unknown source: {exc}')
