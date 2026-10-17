"""Separate read-only demo origin. Share this port, never the unauthenticated dashboard.

Build dashboard first, then: uvicorn backend.app.responder:app --port 8001
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from . import db, maps


@asynccontextmanager
async def lifespan(_):
    db.init()
    maps.store.init()
    yield


app = FastAPI(title='Restricted demo responder view', docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)


@app.middleware('http')
async def privacy_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


app.add_api_route('/api/responder/events/{event_id}', maps.responder_context, methods=['GET'])
dist = maps.ROOT / 'dashboard' / 'dist'
app.mount('/assets', StaticFiles(directory=str(dist / 'assets'), check_dir=False), name='assets')
app.mount('/maps', StaticFiles(directory=str(maps.NETWORK), check_dir=False), name='map-geography')


@app.get('/demo/responder/{event_id}')
def page(event_id: int):
    if not (dist / 'index.html').exists():
        raise HTTPException(503, 'Build the responder UI with npm run build --prefix dashboard')
    return FileResponse(dist / 'index.html')
