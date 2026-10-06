import os
import sys
import time
import logging
import asyncio
import hashlib
import json
from math import pi, sqrt
from threading import Event
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from db import collection, make_skyfield_time, ts
from orbital import EARTH_R, generate_trajectory
from proximity import HAS_NATIVE_MATH
from scanner import full_check, scan_windows, safe_window_proximity_km, WindowVerificationError
from diagnostics import SearchDiagnostics

logging.basicConfig(level=getattr(logging, os.getenv('OPAS_LOG_LEVEL', 'INFO').upper(), logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("opas")

app = FastAPI(title="OPAS – Orbital Proximity Alert System")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

log.info("CORS origins: %s", ALLOWED_ORIGINS)
log.info("Native C++ math (opas_math): %s", "ACTIVE" if HAS_NATIVE_MATH else "FALLBACK to Python")
log.info("Python %s | Workers: %d", sys.version.split()[0], os.cpu_count() or 4)
log.info('Safe-window checks: post-ascent interval detector, 10s discovery refinement, '
         '5s final validation and endpoint/coverage/duration/horizon audits. '
         'OPAS_LOG_LEVEL=DEBUG logs each launch classification.')


@app.middleware('http')
async def request_logging(request: Request, call_next):
    request.state.request_id = uuid4().hex[:12]
    started = time.perf_counter()
    log.info('request=%s | %s %s started', request.state.request_id,
             request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log.exception('request=%s | request failed', request.state.request_id)
        raise
    response.headers['X-Request-ID'] = request.state.request_id
    log.info('request=%s | HTTP %d %s in %.3fs', request.state.request_id,
             response.status_code,
             'stream opened (completion follows in progress log)' if
             request.url.path.endswith('/stream') else 'completed', time.perf_counter()-started)
    return response


@app.get("/debris")
def get_debris():
    docs = list(collection.find({}, {"_id": 0, "tle_line1": 0, "tle_line2": 0}))
    log.info('debris | loaded %d objects for display', len(docs))
    return {"count": len(docs), "debris": docs}


@app.get("/alert")
def alert(
    request: Request,
    target_lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    target_lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    target_alt: float = Query(..., gt=0, allow_inf_nan=False),
    launch_time: str = Query(None),
    inclination: float = Query(None, ge=0, le=180, allow_inf_nan=False),
):
    log.info('request=%s | alert lat=%.3f lon=%.3f alt=%.3f inclination=%s launch=%s',
             request.state.request_id, target_lat, target_lon, target_alt, inclination, launch_time)
    trajectory = None
    if inclination is not None:
        trajectory = generate_trajectory(target_lat, target_lon, target_alt, inclination)

    if launch_time:
        try:
            t = make_skyfield_time(launch_time)
            launch_dt = datetime.fromisoformat(launch_time.replace("Z", "+00:00"))
        except (ValueError, OverflowError) as error:
            raise HTTPException(422, 'Launch time must be a valid ISO timestamp.') from error
        if launch_dt.tzinfo is None:
            launch_dt = launch_dt.replace(tzinfo=timezone.utc)
    else:
        t = ts.now()
        launch_dt = datetime.now(timezone.utc)

    if trajectory:
        candidates = list(collection.find(
            {"altitude_km": {"$gte": 0, "$lte": target_alt + 200}},
            {"_id": 0},
        ))
    else:
        candidates = list(collection.find(
            {"altitude_km": {"$gte": target_alt - 200, "$lte": target_alt + 200}},
            {"_id": 0},
        ))

    threats = full_check(candidates, trajectory, target_lat, target_lon, target_alt, t, launch_dt)
    log.info('request=%s | alert candidates=%d threats=%d waypoints=%d status=%s',
             request.state.request_id, len(candidates), len(threats),
             len(trajectory or []), 'danger' if threats else 'safe')

    result = {
        "status": "danger" if threats else "safe",
        "target_coordinates": {"lat": target_lat, "lon": target_lon, "alt_km": target_alt},
        "candidates_checked": len(candidates),
        "threats": threats,
    }
    if trajectory:
        result["trajectory"] = [
            {"lat": w["lat"], "lng": w["lon"], "alt": w["alt"] / EARTH_R}
            for w in trajectory
        ]
    result["launch_time"] = launch_time or launch_dt.isoformat()
    return result


def _run_window_search(target_lat, target_lon, target_alt, inclination, search_hours, trace):
    trace.update({'phase': 'loading_catalogue', 'parameters': {
        'target_lat': target_lat, 'target_lon': target_lon, 'target_alt': target_alt,
        'inclination': inclination, 'search_hours': search_hours}})
    trajectory = generate_trajectory(target_lat, target_lon, target_alt, inclination)
    t0 = time.perf_counter()
    try:
        candidates = list(collection.find(
            {"altitude_km": {"$gte": target_alt - 100, "$lte": target_alt + 100}},
            {"_id": 0},
        ))
        if not candidates and collection.find_one({}, {'_id': 1}) is None:
            raise WindowVerificationError('The orbital catalogue is empty. Load data before searching.')
    except WindowVerificationError:
        raise
    except Exception as error:
        raise WindowVerificationError('The orbital catalogue could not be read. Check the database connection.') from error
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=search_hours)
    period = 2*pi*sqrt((EARTH_R+target_alt)**3/398600.4418)
    step = period/(len(trajectory)-1)
    diagnostics = {'request_id': trace.data['request_id'], 'search_start_utc': now.isoformat(),
                   'search_end_utc': end.isoformat(), 'candidates_checked': len(candidates),
                   'catalogue_sha256': hashlib.sha256(json.dumps(candidates, sort_keys=True, default=str).encode()).hexdigest(),
                   'catalogue_query_seconds': round(time.perf_counter()-t0, 3),
                   'altitude_filter_km': [target_alt-100, target_alt+100],
                   'trajectory_waypoints': len(trajectory),
                   'flight_start_seconds': round(min(len(trajectory)-1, max(1, round(600/step)))*step, 6),
                   'flight_end_seconds': round(period, 6),
                   'scope': 'Sampled launches in the nominal post-ascent model. '
                            'Intervening launch times, ascent and physical uncertainty are not certified.'}
    trace.update({'phase': 'preparing_orbital_data', **diagnostics})
    windows = scan_windows(
        candidates, trajectory, target_lat, target_lon, target_alt,
        now, end, safe_window_proximity_km(target_alt), verification_step_seconds=5,
        progress=trace.update, diagnostics=diagnostics,
    )
    trace.update({'phase': 'complete', **diagnostics, 'status': 'complete'})
    return {
        "search_hours": search_hours,
        "candidates_checked": len(candidates),
        "windows": windows,
        "diagnostics": dict(trace.data),
    }


@app.get('/safe-windows')
def safe_windows(
    request: Request,
    target_lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    target_lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    target_alt: float = Query(..., gt=0, allow_inf_nan=False),
    inclination: float = Query(..., ge=0, le=180, allow_inf_nan=False),
    search_hours: int = Query(24, ge=1, le=336),
):
    trace = SearchDiagnostics(request.state.request_id)
    try:
        return _run_window_search(target_lat, target_lon, target_alt, inclination, search_hours, trace)
    except WindowVerificationError as error:
        log.warning('request=%s | window verification incomplete: %s', request.state.request_id, error)
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get('/safe-windows/stream')
async def safe_windows_stream(
    request: Request,
    target_lat: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
    target_lon: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
    target_alt: float = Query(..., gt=0, allow_inf_nan=False),
    inclination: float = Query(..., ge=0, le=180, allow_inf_nan=False),
    search_hours: int = Query(24, ge=1, le=336),
):
    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        cancelled = Event()

        def publish(event):
            if cancelled.is_set():
                raise WindowVerificationError('The client disconnected; the window search was cancelled.')
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run():
            trace = SearchDiagnostics(request.state.request_id, publish)
            try:
                result = _run_window_search(target_lat, target_lon, target_alt, inclination, search_hours, trace)
                publish({'event': 'result', 'data': result})
            except Exception as error:
                if cancelled.is_set():
                    log.info('request=%s | disconnected search stopped', request.state.request_id)
                    return
                detail = str(error) if isinstance(error, WindowVerificationError) else 'Window verification failed unexpectedly. Check the request log.'
                log.exception('request=%s | window verification incomplete', request.state.request_id)
                publish({'event': 'error', 'data': {'detail': detail, 'request_id': request.state.request_id,
                                                 'status': 'incomplete'}})

        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ': still working\n\n'
                    continue
                yield 'event: '+event['event']+'\ndata: '+json.dumps(event['data'], allow_nan=False)+'\n\n'
                if event['event'] in ('result', 'error'):
                    break
        finally:
            cancelled.set()
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
