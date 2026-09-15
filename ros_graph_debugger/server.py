"""FastAPI app: REST + WebSocket + AI Markdown, plus the static web UI.

The app is intentionally a thin read layer over RuntimeGraphStore. The rclpy
node fills the store from another thread; here we just serialize and stream it.
"""

from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles

from . import __version__
from .markdown import snapshot_to_markdown
from .model import RuntimeGraphStore
from .scope import ScopeConfig, filter_snapshot


def create_app(store, web_dir: str,
               profile_data: dict | None = None,
               stream_period: float = 1.0,
               replay=None, replay_interval: float = 0.5,
               thresholds=None) -> FastAPI:
    app = FastAPI(title='ros_graph_debugger', version=__version__)

    configured_scope = (profile_data or {}).get('_scope')
    scope = configured_scope \
        if isinstance(configured_scope, ScopeConfig) else ScopeConfig()

    def read_snapshot() -> dict:
        """Read the store once and apply the configured serving view."""
        return filter_snapshot(store.snapshot().to_dict(), scope)

    # A single background task advances the replay cursor, so playback speed is
    # independent of how many browser tabs are connected.
    if replay is not None:
        @app.on_event('startup')
        async def _start_replay_ticker():
            async def _tick():
                while True:
                    await asyncio.sleep(replay_interval)
                    replay.advance()
            app.state._replay_task = asyncio.create_task(_tick())

    # Expose only the UI-relevant parts of the profile and serving scope, not
    # the derived expectation maps used internally.
    profile_public = None
    if profile_data:
        profile_public = {
            'name': profile_data.get('name'),
            'groups': profile_data.get('groups', {}),
        }
        if scope.active:
            profile_public['scope'] = {
                'node_allowlist': scope.effective_node_allowlist,
            }

    # ------------------------------------------------------------- REST API #
    @app.get('/api/v1/health')
    def health():
        return {'status': 'ok', 'version': __version__}

    @app.get('/api/v1/profile')
    def profile():
        return profile_public or {}

    # ------------------------------------------------------- replay control #
    @app.get('/api/v1/replay')
    def replay_state():
        if replay is None:
            return {'mode': 'live'}
        return replay.state()

    @app.post('/api/v1/replay/seek')
    def replay_seek(index: int):
        if replay is None:
            return {'mode': 'live'}
        return replay.seek(index)

    @app.post('/api/v1/replay/play')
    def replay_play(playing: bool = True):
        if replay is None:
            return {'mode': 'live'}
        return replay.set_playing(playing)

    @app.get('/api/v1/snapshot')
    def snapshot():
        return JSONResponse(read_snapshot())

    @app.get('/api/v1/snapshot.md', response_class=PlainTextResponse)
    def snapshot_md(focus: str | None = None):
        return snapshot_to_markdown(read_snapshot(), focus=focus)

    @app.get('/api/v1/graph')
    def graph():
        s = read_snapshot()
        return {'timestamp': s['timestamp'], 'profile': s['profile'],
                'nodes': s['nodes'], 'topics': s['topics'], 'edges': s['edges']}

    @app.get('/api/v1/nodes')
    def nodes():
        return read_snapshot()['nodes']

    @app.get('/api/v1/topics')
    def topics():
        return read_snapshot()['topics']

    @app.get('/api/v1/tf')
    def tf():
        return read_snapshot()['tf_edges']

    @app.get('/api/v1/diagnostics')
    def diagnostics():
        return read_snapshot()['diagnostics']

    @app.get('/api/v1/callbacks')
    def callbacks():
        return read_snapshot().get('callbacks', [])

    @app.get('/api/v1/issues')
    def issues():
        return read_snapshot()['issues']

    @app.get('/api/v1/summary')
    def summary():
        from .health import summarize_health
        return summarize_health(read_snapshot())

    @app.get('/api/v1/path')
    def path(target: str):
        from .pipeline import trace_pipeline_path
        p = trace_pipeline_path(read_snapshot(), target)
        if p is None:
            return JSONResponse(
                {'error': f'no connected path through {target!r}'},
                status_code=404)
        return p

    # ------------------------------------------------- live config (tuning) #
    @app.get('/api/v1/config')
    def get_config():
        if thresholds is None:
            return {}
        from .config import config_to_dict
        return config_to_dict(thresholds)

    @app.post('/api/v1/config')
    async def post_config(request: Request):
        if thresholds is None:
            return JSONResponse({'error': 'config not available in this mode'},
                                status_code=400)
        from .config import apply_config
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({'error': 'invalid JSON'}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({'error': 'expected a JSON object'}, status_code=400)
        return {'changed': apply_config(thresholds, payload)}

    # ------------------------------------------------------------ WebSocket #
    @app.websocket('/api/v1/stream')
    async def stream(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                payload = json.dumps(read_snapshot())
                await ws.send_text(payload)
                await asyncio.sleep(stream_period)
        except WebSocketDisconnect:
            return
        except Exception:
            return

    # --------------------------------------------------------------- web UI #
    if os.path.isdir(web_dir):
        @app.get('/', response_class=HTMLResponse)
        def index():
            return FileResponse(os.path.join(web_dir, 'index.html'))

        app.mount('/', StaticFiles(directory=web_dir, html=True), name='web')
    else:
        @app.get('/', response_class=HTMLResponse)
        def index_missing():
            return HTMLResponse(
                '<h1>ros_graph_debugger</h1><p>Web assets not found at '
                f'<code>{web_dir}</code>. The REST API is available under '
                '<code>/api/v1/</code>.</p>')

    return app
