"""
FastAPI entry point: dashboard, HTMX scan triggers, settings, and scheduled scans.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import nulls_last, select
from sqlalchemy.orm import Session

from database import SessionLocal, get_db, init_db
from models import Config, Episode, Media
from scanner import (
    load_setting,
    run_scan_movies_background,
    run_scan_tv_background,
    scan_state,
    scheduled_full_scan,
)
from settings import settings, validate_api_credentials

BASE_DIR = Path(__file__).resolve().parent

POSTER_DIR = settings.resolved_poster_dir()
POSTER_DIR.mkdir(parents=True, exist_ok=True)


def ensure_runtime_directories() -> None:
    for path in settings.runtime_directories_to_create():
        path.mkdir(parents=True, exist_ok=True)


_logger = logging.getLogger("open_media_tracker")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

scheduler = BackgroundScheduler()


def seed_defaults(db: Session) -> None:
    pairs = [
        ("LIBRARY_TV_PATH", settings.library_tv_path),
        ("LIBRARY_MOVIES_PATH", settings.library_movies_path),
        ("TMDB_READ_ACCESS_TOKEN", settings.tmdb_read_access_token),
        ("TMDB_API_KEY", settings.tmdb_api_key),
        ("TVDB_API_KEY", settings.tvdb_api_key),
        ("TVDB_PIN", settings.tvdb_pin),
        ("SCAN_INTERVAL_MINUTES", settings.scan_interval_minutes),
    ]
    for key, val in pairs:
        row = db.execute(select(Config).where(Config.key == key)).scalar_one_or_none()
        if row is None:
            db.add(Config(key=key, value=val or ""))
    db.commit()


def _interval_minutes(db: Session) -> int:
    raw = load_setting(db, "SCAN_INTERVAL_MINUTES", "360") or "360"
    try:
        v = int(raw)
        return max(15, v)
    except ValueError:
        return 360


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    if not validate_api_credentials(settings, _logger):
        _logger.error(
            "[Open Media Tracker] Startup aborted: fix the environment variables above and restart.",
        )
        raise SystemExit(1)

    ensure_runtime_directories()
    init_db()
    db = SessionLocal()
    try:
        seed_defaults(db)
        mins = _interval_minutes(db)
    finally:
        db.close()

    scheduler.add_job(
        lambda: scheduled_full_scan(str(POSTER_DIR)),
        "interval",
        minutes=mins,
        id="library_scan",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()

    port = settings.app_port
    ready_msg = f"Ready at http://localhost:{port}"
    print(ready_msg, flush=True)
    _logger.info("[Open Media Tracker] %s", ready_msg)

    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Open Media Tracker", lifespan=lifespan)
app.mount("/posters", StaticFiles(directory=str(POSTER_DIR)), name="posters")


def _is_htmx(request: Request) -> bool:
    return (request.headers.get("hx-request") or "").lower() == "true"


def _settings_dict(db: Session) -> dict[str, str]:
    return {
        "LIBRARY_TV_PATH": load_setting(db, "LIBRARY_TV_PATH", "") or "",
        "LIBRARY_MOVIES_PATH": load_setting(db, "LIBRARY_MOVIES_PATH", "") or "",
        "TMDB_READ_ACCESS_TOKEN": load_setting(db, "TMDB_READ_ACCESS_TOKEN", "") or "",
        "TMDB_API_KEY": load_setting(db, "TMDB_API_KEY", "") or "",
        "TVDB_API_KEY": load_setting(db, "TVDB_API_KEY", "") or "",
        "TVDB_PIN": load_setting(db, "TVDB_PIN", "") or "",
        "SCAN_INTERVAL_MINUTES": load_setting(db, "SCAN_INTERVAL_MINUTES", "360") or "360",
    }


def _media_select_ordered():
    return select(Media).order_by(nulls_last(Media.title.asc()), Media.folder_name.asc())


@app.get("/health")
def health() -> dict[str, str]:
    """Lightweight probe for Docker healthchecks and reverse proxies."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/tv", status_code=302)


@app.get("/movies", response_class=HTMLResponse)
def page_movies(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        _media_select_ordered().where(Media.media_type == "movie"),
    ).scalars().all()
    ctx: dict = {
        "active_nav": "movies",
        "settings": _settings_dict(db),
        "media_rows": rows,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/main_movies.html", ctx)
    return templates.TemplateResponse(request, "pages/movies.html", ctx)


@app.get("/tv", response_class=HTMLResponse)
def page_tv(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        _media_select_ordered().where(Media.media_type == "tv"),
    ).scalars().all()
    ctx: dict = {
        "active_nav": "tv",
        "settings": _settings_dict(db),
        "media_rows": rows,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/main_tv.html", ctx)
    return templates.TemplateResponse(request, "pages/tv.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request, db: Session = Depends(get_db)):
    toast = None
    if request.query_params.get("saved") == "1":
        toast = "Settings saved."
    ctx: dict = {
        "active_nav": "settings",
        "settings": _settings_dict(db),
        "toast": toast,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "partials/main_settings.html", ctx)
    return templates.TemplateResponse(request, "pages/settings.html", ctx)


@app.get("/tv/{show_id}/audit", response_class=HTMLResponse)
def tv_show_audit(request: Request, show_id: int, db: Session = Depends(get_db)):
    media = db.get(Media, show_id)
    if media is None or media.media_type != "tv":
        raise HTTPException(status_code=404, detail="TV show not found")
    missing = db.execute(
        select(Episode)
        .where(Episode.media_id == show_id, Episode.exists_locally.is_(False))
        .order_by(Episode.season_number, Episode.episode_number),
    ).scalars().all()
    missing_count = len(missing)
    ctx = {
        "show": media,
        "missing_episodes": missing,
        "missing_count": missing_count,
    }
    return templates.TemplateResponse(request, "partials/tv_audit.html", ctx)


@app.get("/fragments/movies-table", response_class=HTMLResponse)
def fragment_movies_table(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        _media_select_ordered().where(Media.media_type == "movie"),
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "partials/movies_table.html",
        {"media_rows": rows},
    )


@app.get("/fragments/tv-table", response_class=HTMLResponse)
def fragment_tv_table(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        _media_select_ordered().where(Media.media_type == "tv"),
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "partials/tv_table.html",
        {"media_rows": rows},
    )


@app.get("/fragments/tv-audit-empty", response_class=HTMLResponse)
def fragment_tv_audit_empty(request: Request):
    return templates.TemplateResponse(request, "partials/tv_audit_empty.html", {})


@app.get("/fragments/scan-tv-status", response_class=HTMLResponse)
def fragment_scan_tv(request: Request):
    with scan_state.lock:
        running = scan_state.running_tv
        phase = scan_state.phase_tv
        msg = scan_state.message_tv
        cur = scan_state.processed_tv
        tot = scan_state.total_tv
        errs = list(scan_state.errors_tv)
    pct = int(100 * cur / tot) if tot else 0
    return templates.TemplateResponse(
        request,
        "partials/scan_tv.html",
        {"running": running, "phase": phase, "message": msg, "current": cur, "total": tot, "percent": pct, "errors": errs},
    )


@app.get("/fragments/scan-movie-status", response_class=HTMLResponse)
def fragment_scan_movie(request: Request):
    with scan_state.lock:
        running = scan_state.running_movie
        phase = scan_state.phase_movie
        msg = scan_state.message_movie
        cur = scan_state.processed_movie
        tot = scan_state.total_movie
        errs = list(scan_state.errors_movie)
    pct = int(100 * cur / tot) if tot else 0
    return templates.TemplateResponse(
        request,
        "partials/scan_movie.html",
        {
            "running": running,
            "phase": phase,
            "message": msg,
            "current": cur,
            "total": tot,
            "percent": pct,
            "errors": errs,
        },
    )


@app.post("/scan/tv", response_class=HTMLResponse)
def trigger_scan_tv(request: Request):
    run_scan_tv_background(str(POSTER_DIR))
    return templates.TemplateResponse(request, "partials/scan_tv.html", _stub_scan_tv_started())


@app.post("/scan/movies", response_class=HTMLResponse)
def trigger_scan_movies(request: Request):
    run_scan_movies_background(str(POSTER_DIR))
    return templates.TemplateResponse(request, "partials/scan_movie.html", _stub_scan_movie_started())


def _stub_scan_tv_started() -> dict:
    with scan_state.lock:
        running = scan_state.running_tv
        phase = scan_state.phase_tv or "Queued"
        msg = scan_state.message_tv
        cur = scan_state.processed_tv
        tot = scan_state.total_tv
        errs = list(scan_state.errors_tv)
    pct = int(100 * cur / tot) if tot else 0
    return {"running": running, "phase": phase, "message": msg, "current": cur, "total": tot, "percent": pct, "errors": errs}


def _stub_scan_movie_started() -> dict:
    with scan_state.lock:
        running = scan_state.running_movie
        phase = scan_state.phase_movie or "Queued"
        msg = scan_state.message_movie
        cur = scan_state.processed_movie
        tot = scan_state.total_movie
        errs = list(scan_state.errors_movie)
    pct = int(100 * cur / tot) if tot else 0
    return {
        "running": running,
        "phase": phase,
        "message": msg,
        "current": cur,
        "total": tot,
        "percent": pct,
        "errors": errs,
    }


@app.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    library_tv_path: str = Form(""),
    library_movies_path: str = Form(""),
    tmdb_read_access_token: str = Form(""),
    tmdb_api_key: str = Form(""),
    tvdb_api_key: str = Form(""),
    tvdb_pin: str = Form(""),
    scan_interval_minutes: str = Form("360"),
):
    updates = {
        "LIBRARY_TV_PATH": library_tv_path.strip(),
        "LIBRARY_MOVIES_PATH": library_movies_path.strip(),
        "TMDB_READ_ACCESS_TOKEN": tmdb_read_access_token.strip(),
        "TMDB_API_KEY": tmdb_api_key.strip(),
        "TVDB_API_KEY": tvdb_api_key.strip(),
        "TVDB_PIN": tvdb_pin.strip(),
        "SCAN_INTERVAL_MINUTES": scan_interval_minutes.strip() or "360",
    }
    for key, val in updates.items():
        row = db.execute(select(Config).where(Config.key == key)).scalar_one_or_none()
        if row:
            row.value = val
        else:
            db.add(Config(key=key, value=val))
    db.commit()

    if scheduler.get_job("library_scan"):
        scheduler.reschedule_job(
            "library_scan",
            trigger=IntervalTrigger(minutes=_interval_minutes(db)),
        )

    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "partials/main_settings.html",
            {
                "active_nav": "settings",
                "settings": _settings_dict(db),
                "settings_saved_banner": "Settings saved.",
            },
        )
    return RedirectResponse(url="/settings?saved=1", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.app_port)
