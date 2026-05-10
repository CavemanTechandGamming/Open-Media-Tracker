"""
Shallow library scanning: only os.scandir top-level folders vs stored mtime.
TMDB/TVDB lookups and local episode enumeration run only when a folder is new or changed.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Config, Episode, Media

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".mov", ".webm", ".mpeg", ".mpg"})
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# S01E01 / s1e2 / 1x01
_EP_PATTERNS = [
    re.compile(r"(?:^|[.\s_-])[Ss](\d{1,2})[^0-9]{0,3}[Ee](\d{1,3})(?:[^0-9]|$)"),
    re.compile(r"(?:^|[.\s_-])(\d{1,2})[xX](\d{1,3})(?:[^0-9]|$)"),
]


def _mtime_key(st_mtime: float) -> float:
    return round(float(st_mtime), 6)


def _safe_tmdb_id(found: dict[str, Any], folder_label: str) -> int | None:
    """Avoid crashing on odd folder names or malformed API payloads."""
    raw = found.get("id")
    try:
        i = int(raw)
        return i if i > 0 else None
    except (TypeError, ValueError):
        logger.warning("Skipping TMDB id parse for %s: %r", folder_label, raw)
        return None


def _safe_external_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_episode_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ScanState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running_tv: bool = False
    running_movie: bool = False
    phase_tv: str = ""
    phase_movie: str = ""
    message_tv: str = ""
    message_movie: str = ""
    processed_tv: int = 0
    total_tv: int = 0
    processed_movie: int = 0
    total_movie: int = 0
    errors_tv: list[str] = field(default_factory=list)
    errors_movie: list[str] = field(default_factory=list)


scan_state = ScanState()


def load_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.execute(select(Config).where(Config.key == key)).scalar_one_or_none()
    if row and row.value is not None and row.value != "":
        return row.value
    return os.getenv(key, default)


class TMDBClient:
    """TMDB API v3 — Bearer read token (preferred) or legacy `api_key` query param."""

    def __init__(
        self,
        *,
        read_access_token: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base = "https://api.themoviedb.org/3"
        rt = (read_access_token or "").strip()
        ak = (api_key or "").strip()
        if rt:
            self.headers = {"accept": "application/json", "Authorization": f"Bearer {rt}"}
            self._params_extra: dict[str, str] = {}
        elif ak:
            self.headers = {"accept": "application/json"}
            self._params_extra = {"api_key": ak}
        else:
            raise ValueError("TMDB requires TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY")

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        return {**self._params_extra, **kwargs}

    def search_tv(self, query: str) -> dict[str, Any] | None:
        r = requests.get(
            f"{self.base}/search/tv",
            headers=self.headers,
            params=self._params(query=query),
            timeout=60,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        return results[0] if results else None

    def search_movie(self, query: str) -> dict[str, Any] | None:
        r = requests.get(
            f"{self.base}/search/movie",
            headers=self.headers,
            params=self._params(query=query),
            timeout=60,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        return results[0] if results else None

    def tv_detail(self, tv_id: int) -> dict[str, Any]:
        r = requests.get(
            f"{self.base}/tv/{tv_id}",
            headers=self.headers,
            params=self._params(append_to_response="external_ids"),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def movie_detail(self, movie_id: int) -> dict[str, Any]:
        r = requests.get(
            f"{self.base}/movie/{movie_id}",
            headers=self.headers,
            params=self._params(append_to_response="external_ids"),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def tv_season(self, tv_id: int, season_number: int) -> dict[str, Any]:
        r = requests.get(
            f"{self.base}/tv/{tv_id}/season/{season_number}",
            headers=self.headers,
            params=self._params(),
            timeout=60,
        )
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()


def build_tmdb_client(tmdb_read_access_token: str | None, tmdb_api_key: str | None) -> TMDBClient:
    rt = (tmdb_read_access_token or "").strip()
    ak = (tmdb_api_key or "").strip()
    if rt:
        return TMDBClient(read_access_token=rt)
    if ak:
        return TMDBClient(api_key=ak)
    raise ValueError("Set TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY (see .env.example)")


class TVDBClient:
    """TVDB v4 — optional; used for series status cross-check when credentials exist."""

    def __init__(self, api_key: str, pin: str | None = None) -> None:
        self.api_key = api_key
        self.pin = (pin or "").strip() or None
        self._token: str | None = None
        self._token_expires: float = 0.0
        self.base = "https://api4.thetvdb.com/v4"

    def _ensure_token(self) -> bool:
        if self._token and time.time() < self._token_expires - 60:
            return True
        try:
            payload: dict[str, str] = {"apikey": self.api_key}
            if self.pin:
                payload["pin"] = self.pin
            r = requests.post(
                f"{self.base}/login",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json().get("data") or {}
            token = data.get("token")
            if not token:
                return False
            self._token = token
            self._token_expires = time.time() + 29 * 24 * 3600
            return True
        except requests.RequestException as e:
            logger.warning("TVDB login failed: %s", e)
            return False

    def series_extended(self, tvdb_id: int) -> dict[str, Any] | None:
        if not self._ensure_token() or not self._token:
            return None
        try:
            r = requests.get(
                f"{self.base}/series/{tvdb_id}/extended",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=60,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get("data")
        except requests.RequestException as e:
            logger.warning("TVDB series fetch failed: %s", e)
            return None


def parse_episode_keys_from_filename(name: str) -> set[tuple[int, int]]:
    stem = os.path.splitext(name)[0]
    found: set[tuple[int, int]] = set()
    for rx in _EP_PATTERNS:
        for m in rx.finditer(stem):
            found.add((int(m.group(1)), int(m.group(2))))
    return found


def folder_has_any_video(root_folder: str) -> bool:
    for _, _, filenames in os.walk(root_folder):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in VIDEO_EXTENSIONS:
                return True
    return False


def collect_local_episode_keys(root_folder: str) -> set[tuple[int, int]]:
    """Walk tree under a show folder only when API refresh runs (not on every shallow pass)."""
    keys: set[tuple[int, int]] = set()
    for dirpath, _, filenames in os.walk(root_folder):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            keys |= parse_episode_keys_from_filename(fn)
    return keys


def download_poster_thumbnail(
    poster_path: str | None,
    dest_path: str,
    max_width: int = 220,
) -> str | None:
    if not poster_path:
        return None
    url = f"{TMDB_IMAGE_BASE}{poster_path}"
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        w, h = img.size
        if w > max_width:
            nh = int(h * (max_width / w))
            img = img.resize((max_width, nh), Image.Resampling.LANCZOS)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        img.save(dest_path, format="JPEG", quality=82, optimize=True)
        return dest_path
    except (requests.RequestException, OSError, ValueError) as e:
        logger.warning("Poster download failed: %s", e)
        return None


def _merge_tvdb_status(tvdb: TVDBClient | None, tvdb_id: int | None, tmdb_status: str | None) -> str | None:
    if not tvdb_id or not tvdb:
        return tmdb_status
    ext = tvdb.series_extended(tvdb_id)
    if not ext:
        return tmdb_status
    st = ext.get("status") or {}
    name = st.get("name") if isinstance(st, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return tmdb_status


def refresh_tv_show(
    db: Session,
    media_row: Media,
    folder_path: str,
    folder_mtime: float,
    tmdb: TMDBClient,
    tvdb: TVDBClient | None,
    poster_dir: str,
) -> None:
    query_name = media_row.folder_name.replace(".", " ").strip()
    found = tmdb.search_tv(query_name)
    if not found:
        media_row.title = media_row.folder_name
        media_row.tmdb_id = None
        media_row.tvdb_id = None
        media_row.status = None
        media_row.folder_mtime = folder_mtime
        media_row.last_api_sync = datetime.now(timezone.utc)
        media_row.last_error = "No TMDB match for folder name"
        return

    tv_id = _safe_tmdb_id(found, folder_path)
    if tv_id is None:
        media_row.title = media_row.folder_name
        media_row.last_api_sync = datetime.now(timezone.utc)
        media_row.last_error = "Invalid TMDB search response (missing id)"
        media_row.folder_mtime = folder_mtime
        return

    detail = tmdb.tv_detail(tv_id)
    external = detail.get("external_ids") or {}
    tvdb_id = external.get("tvdb_id")
    tvdb_id_int = _safe_external_int(tvdb_id)

    status = detail.get("status") or None
    status = _merge_tvdb_status(tvdb, tvdb_id_int, status)

    seasons_api: dict[tuple[int, int], str | None] = {}
    try:
        num_seasons = int(detail.get("number_of_seasons") or 0)
    except (TypeError, ValueError):
        num_seasons = 0
    for sn in range(1, num_seasons + 1):
        season = tmdb.tv_season(tv_id, sn)
        for ep in season.get("episodes") or []:
            en = _safe_episode_number(ep.get("episode_number"))
            if en is None:
                continue
            seasons_api[(sn, en)] = ep.get("name")

    local_keys = collect_local_episode_keys(folder_path)
    present = 0
    db.query(Episode).filter(Episode.media_id == media_row.id).delete(synchronize_session=False)
    for (sn, en) in sorted(seasons_api.keys()):
        title = seasons_api[(sn, en)]
        key = (sn, en)
        exists = key in local_keys
        if exists:
            present += 1
        db.add(
            Episode(
                media_id=media_row.id,
                season_number=sn,
                episode_number=en,
                title=title,
                exists_locally=exists,
            )
        )

    poster_fs = os.path.join(poster_dir, f"{media_row.id}.jpg")
    saved = download_poster_thumbnail(detail.get("poster_path"), poster_fs)
    poster_web = f"/posters/{media_row.id}.jpg" if saved else None

    media_row.folder_mtime = folder_mtime
    media_row.title = detail.get("name") or media_row.folder_name
    media_row.tmdb_id = tv_id
    media_row.tvdb_id = tvdb_id_int
    media_row.status = status
    media_row.poster_local = poster_web
    media_row.total_episodes_api = len(seasons_api)
    media_row.episodes_present_local = present
    media_row.last_api_sync = datetime.now(timezone.utc)
    media_row.last_error = None


def refresh_movie(
    db: Session,
    media_row: Media,
    folder_path: str,
    folder_mtime: float,
    tmdb: TMDBClient,
    poster_dir: str,
) -> None:
    query_name = media_row.folder_name.replace(".", " ").strip()
    found = tmdb.search_movie(query_name)
    if not found:
        media_row.title = media_row.folder_name
        media_row.tmdb_id = None
        media_row.tvdb_id = None
        media_row.status = None
        media_row.folder_mtime = folder_mtime
        media_row.last_api_sync = datetime.now(timezone.utc)
        media_row.last_error = "No TMDB match for folder name"
        media_row.total_episodes_api = 0
        media_row.episodes_present_local = 0
        return

    mid = _safe_tmdb_id(found, folder_path)
    if mid is None:
        media_row.title = media_row.folder_name
        media_row.last_api_sync = datetime.now(timezone.utc)
        media_row.last_error = "Invalid TMDB search response (missing id)"
        media_row.folder_mtime = folder_mtime
        media_row.total_episodes_api = 0
        media_row.episodes_present_local = 0
        return

    detail = tmdb.movie_detail(mid)
    status = detail.get("status")

    poster_fs = os.path.join(poster_dir, f"{media_row.id}.jpg")
    saved = download_poster_thumbnail(detail.get("poster_path"), poster_fs)
    poster_web = f"/posters/{media_row.id}.jpg" if saved else None

    media_row.folder_mtime = folder_mtime
    media_row.title = detail.get("title") or media_row.folder_name
    media_row.tmdb_id = mid
    media_row.tvdb_id = None
    media_row.status = status
    media_row.poster_local = poster_web
    media_row.total_episodes_api = 1
    media_row.episodes_present_local = 1 if folder_has_any_video(folder_path) else 0
    media_row.last_api_sync = datetime.now(timezone.utc)
    media_row.last_error = None


def _iter_top_level_dirs(root: str) -> list[tuple[str, str, float]]:
    if not root or not os.path.isdir(root):
        return []
    out: list[tuple[str, str, float]] = []
    with os.scandir(root) as it:
        for entry in it:
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            out.append((entry.name, entry.path, _mtime_key(st.st_mtime)))
    out.sort(key=lambda x: x[0].lower())
    return out


def scan_library(
    db: Session,
    media_type: str,
    root_path: str,
    tmdb_read_access_token: str | None,
    tmdb_api_key: str | None,
    tvdb_api_key: str | None,
    tvdb_pin: str | None,
    poster_dir: str,
    on_progress: Callable[[str, str, int, int], None] | None = None,
    error_collector: list[str] | None = None,
) -> None:
    tmdb = build_tmdb_client(tmdb_read_access_token, tmdb_api_key)
    tv_key = (tvdb_api_key or "").strip()
    tv_pin = (tvdb_pin or "").strip() or None
    tvdb = TVDBClient(tv_key, tv_pin) if tv_key else None

    entries = _iter_top_level_dirs(root_path)
    total = len(entries)
    for idx, (folder_name, folder_path, mtime_key) in enumerate(entries, start=1):
        if on_progress:
            on_progress("Walking libraries", folder_name, idx, total)

        existing = db.execute(select(Media).where(Media.folder_path == folder_path)).scalar_one_or_none()

        if existing:
            type_fix = existing.media_type != media_type
            if type_fix:
                existing.media_type = media_type
            if _mtime_key(existing.folder_mtime) == mtime_key and existing.last_api_sync is not None:
                if type_fix:
                    db.commit()
                continue
        else:
            existing = Media(
                folder_name=folder_name,
                folder_path=folder_path,
                folder_mtime=mtime_key,
                media_type=media_type,
            )
            db.add(existing)
            db.flush()

        try:
            if media_type == "tv":
                refresh_tv_show(db, existing, folder_path, mtime_key, tmdb, tvdb, poster_dir)
            else:
                refresh_movie(db, existing, folder_path, mtime_key, tmdb, poster_dir)
        except requests.HTTPError as e:
            msg = f"{folder_name}: HTTP {e.response.status_code if e.response else '?'}"
            logger.exception(msg)
            existing.last_error = msg
            existing.folder_mtime = mtime_key
            if error_collector is not None:
                error_collector.append(msg)
        except requests.RequestException as e:
            msg = f"{folder_name}: {e}"
            logger.exception(msg)
            existing.last_error = msg
            existing.folder_mtime = mtime_key
            if error_collector is not None:
                error_collector.append(msg)
        except Exception as e:
            msg = f"{folder_name}: {type(e).__name__}: {e}"
            logger.exception(msg)
            existing.last_error = msg[:2048]
            existing.folder_mtime = mtime_key
            if error_collector is not None:
                error_collector.append(msg[:500])

        db.commit()

    if on_progress:
        on_progress("Done", "", total, total)


def run_scan_tv_background(app_poster_dir: str) -> None:
    def worker() -> None:
        from database import SessionLocal

        with scan_state.lock:
            if scan_state.running_tv:
                return
            scan_state.running_tv = True
            scan_state.phase_tv = "Starting"
            scan_state.message_tv = ""
            scan_state.processed_tv = 0
            scan_state.total_tv = 0
            scan_state.errors_tv = []

        try:
            db = SessionLocal()
            try:
                root = load_setting(db, "LIBRARY_TV_PATH", "") or ""
                tmdb_token = load_setting(db, "TMDB_READ_ACCESS_TOKEN", "") or ""
                tmdb_key = load_setting(db, "TMDB_API_KEY", "") or ""
                tvdb_key = load_setting(db, "TVDB_API_KEY", "") or None
                tvdb_pin = load_setting(db, "TVDB_PIN", "") or None

                entries = _iter_top_level_dirs(root)

                def prog(phase: str, msg: str, cur: int, tot: int) -> None:
                    with scan_state.lock:
                        scan_state.phase_tv = phase
                        scan_state.message_tv = msg
                        scan_state.processed_tv = cur
                        scan_state.total_tv = tot

                prog("Scanning TV", "", 0, max(len(entries), 1))
                try:
                    scan_library(
                        db,
                        "tv",
                        root,
                        tmdb_token,
                        tmdb_key,
                        tvdb_key,
                        tvdb_pin,
                        app_poster_dir,
                        on_progress=prog,
                        error_collector=scan_state.errors_tv,
                    )
                except ValueError as e:
                    with scan_state.lock:
                        scan_state.phase_tv = "Error"
                        scan_state.message_tv = str(e)
                        scan_state.errors_tv.append(str(e))
                prog("Done", "", scan_state.total_tv, scan_state.total_tv)
            finally:
                db.close()
        finally:
            with scan_state.lock:
                scan_state.running_tv = False

    threading.Thread(target=worker, daemon=True).start()


def run_scan_movies_background(app_poster_dir: str) -> None:
    def worker() -> None:
        from database import SessionLocal

        with scan_state.lock:
            if scan_state.running_movie:
                return
            scan_state.running_movie = True
            scan_state.phase_movie = "Starting"
            scan_state.message_movie = ""
            scan_state.processed_movie = 0
            scan_state.total_movie = 0
            scan_state.errors_movie = []

        try:
            db = SessionLocal()
            try:
                root = load_setting(db, "LIBRARY_MOVIES_PATH", "") or ""
                tmdb_token = load_setting(db, "TMDB_READ_ACCESS_TOKEN", "") or ""
                tmdb_key = load_setting(db, "TMDB_API_KEY", "") or ""

                entries = _iter_top_level_dirs(root)

                def prog(phase: str, msg: str, cur: int, tot: int) -> None:
                    with scan_state.lock:
                        scan_state.phase_movie = phase
                        scan_state.message_movie = msg
                        scan_state.processed_movie = cur
                        scan_state.total_movie = tot

                prog("Scanning Movies", "", 0, max(len(entries), 1))
                try:
                    scan_library(
                        db,
                        "movie",
                        root,
                        tmdb_token,
                        tmdb_key,
                        None,
                        None,
                        app_poster_dir,
                        on_progress=prog,
                        error_collector=scan_state.errors_movie,
                    )
                except ValueError as e:
                    with scan_state.lock:
                        scan_state.phase_movie = "Error"
                        scan_state.message_movie = str(e)
                        scan_state.errors_movie.append(str(e))
                prog("Done", "", scan_state.total_movie, scan_state.total_movie)
            finally:
                db.close()
        finally:
            with scan_state.lock:
                scan_state.running_movie = False

    threading.Thread(target=worker, daemon=True).start()


def scheduled_full_scan(app_poster_dir: str) -> None:
    """Background job: shallow pass for both libraries (respects mtime gate inside scan_library)."""

    from database import SessionLocal

    db = SessionLocal()
    try:
        tmdb_token = load_setting(db, "TMDB_READ_ACCESS_TOKEN", "") or ""
        tmdb_key = load_setting(db, "TMDB_API_KEY", "") or ""
        if not (tmdb_token or "").strip() and not (tmdb_key or "").strip():
            logger.warning("Scheduled scan skipped: set TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY")
            return
        tv_root = load_setting(db, "LIBRARY_TV_PATH", "") or ""
        mv_root = load_setting(db, "LIBRARY_MOVIES_PATH", "") or ""
        tvdb_key = load_setting(db, "TVDB_API_KEY", "") or None
        tvdb_pin = load_setting(db, "TVDB_PIN", "") or None
        poster_dir = app_poster_dir

        def noop(_p: str, _m: str, _c: int, _t: int) -> None:
            pass

        if tv_root:
            scan_library(db, "tv", tv_root, tmdb_token, tmdb_key, tvdb_key, tvdb_pin, poster_dir, on_progress=noop)
        if mv_root:
            scan_library(db, "movie", mv_root, tmdb_token, tmdb_key, None, None, poster_dir, on_progress=noop)
    except Exception:
        logger.exception("Scheduled scan failed")
    finally:
        db.close()
