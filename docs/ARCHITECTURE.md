# Architecture — Open Media Tracker

This document describes how the application is structured internally: shallow scanning, persistence, and external APIs.

---

## High-level diagram

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Browser   │────▶│   FastAPI    │────▶│ SQLite (SQLAlch.)│
│  HTMX UI    │◀────│   Jinja2     │◀────│  media, episodes │
└─────────────┘     └──────┬───────┘     │  config          │
                           │             └─────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌─────────────┐
       │ scanner  │ │ APSched. │ │ StaticFiles │
       │ module   │ │ interval │ │ /posters    │
       └────┬─────┘ └──────────┘ └─────────────┘
            │
     ┌──────┴──────┐
     ▼             ▼
┌─────────┐   ┌─────────┐
│  TMDB   │   │  TVDB   │  (optional)
│  API v3 │   │  API v4 │
└─────────┘   └─────────┘
```

---

## Data flow: shallow scan

The design goal is to stay efficient on **very large libraries** (for example, multi-terabyte arrays of files) by **not** deep-walking the tree on every pass.

### 1. Top-level directory enumeration

For each configured root (`LIBRARY_TV_PATH`, `LIBRARY_MOVIES_PATH`), the scanner uses **`os.scandir()`** on that root only. Each **immediate child that is a directory** becomes one logical title (one TV series or one movie).

### 2. Modification time gate

For each folder path, the scanner reads **`st_mtime`** (via `stat()` on the `DirEntry`), normalized to a rounded float for stable comparisons. It compares this value to the **`folder_mtime`** stored on the corresponding `Media` row in SQLite.

- **If the row exists and `mtime` matches** and a prior successful API sync timestamp exists → **no TMDB/TVDB calls** and **no recursive file walk** for that folder on this pass.
- **If the folder is new or `mtime` differs** → the scanner performs metadata refresh (and TV-specific local episode detection—see below).

This is the core **“shallow scan”**: the expensive work is **gated** on filesystem change at the **show/movie folder** boundary.

### 3. What happens when a folder is “dirty”

**TV**

1. Search TMDB by folder name (sanitized).
2. Fetch show details, external IDs (including TVDB id when present).
3. Optionally call TVDB extended series if credentials exist.
4. For each season from TMDB, fetch season JSON and build the authoritative episode list.
5. **Only now** walk **under that folder** recursively to find video files and parse `SxxEyy` / `NxNN`-style patterns into `(season, episode)` keys.
6. Upsert `Episode` rows and counts (`total_episodes_api`, `episodes_present_local`).
7. Download poster, resize, save under `data/posters/`.

**Movies**

1. TMDB movie search + detail.
2. Poster caching as above.
3. Presence is a simple **“any video extension under the folder”** check.

### 4. Manual vs scheduled scans

Both **HTTP-triggered scans** (HTMX buttons) and **APScheduler** jobs call the same **`scan_library`** routine. The **mtime gate** applies in every case, so periodic runs remain cheap when nothing under a top-level folder has changed.

---

## Database schema (conceptual)

SQLite holds three logical tables (see `models.py` for exact columns).

### `media`

One row per **top-level library folder** that has been seen.

- Identity: `folder_path` (unique), `folder_name`, `media_type` (`tv` | `movie`).
- Sync: `folder_mtime`, `last_api_sync`, `last_error`.
- External IDs: `tmdb_id`, `tvdb_id`.
- Display: `title`, `status`, `poster_local` (URL path served by the app).
- TV aggregates: `total_episodes_api`, `episodes_present_local`.

### `episodes`

Child rows for **TV** shows after a successful refresh.

- Foreign key: `media_id` → `media.id`.
- Keys: `season_number`, `episode_number`, optional `title`.
- `exists_locally`: whether a matching file was found under the show folder.

### `config`

Key/value settings overridden by the UI or seeded from the environment (`LIBRARY_*`, `TMDB_*`, `TVDB_*`, `SCAN_INTERVAL_MINUTES`, etc.).

---

## API integration (TMDB / TVDB)

### TMDB

- Uses **API v3** (`api.themoviedb.org/3`).
- Authentication supports either:
  - **Bearer** header (`TMDB_READ_ACCESS_TOKEN`), or
  - **`api_key`** query parameter (`TMDB_API_KEY`),
  with **read token preferred** when both are configured (`build_tmdb_client` in `scanner.py`).
- Images are fetched from TMDB’s CDN once per refresh, then **stored locally** as thumbnails (no reliance on hotlinking in the UI).

### TVDB

- Optional **v4** client (`api4.thetvdb.com/v4`).
- **Login** POST sends `apikey` and optionally **`pin`** (`TVDB_PIN`) when set.
- Bearer token from login is reused until expiry (in-memory client instance).

### Rate limiting and reliability (current behavior)

The codebase **does not implement a dedicated rate limiter or automatic exponential backoff** today. Instead, it **reduces load by design**:

- API calls happen **only** for folders that fail the **mtime gate** or are new.
- Requests for a given refresh are effectively **sequential** (per folder, per season), which naturally spaces traffic compared to aggressive parallel crawlers.

If TMDB or TVDB returns **HTTP errors**, those are logged and surfaced on the **`Media` row** (`last_error`) and may appear in scan progress panels. Operators can **lower scan frequency**, **split libraries**, or retry later.

**Improvement candidates** (see README roadmap): centralized retry with `Retry-After`, configurable concurrency caps, and telemetry on 429 responses.

---

## HTTP surface (FastAPI)

| Area | Role |
|------|------|
| `GET /` | Dashboard (library table + settings). |
| `GET /health` | JSON `{"status":"ok"}` for Docker healthchecks and proxies. |
| `GET /fragments/*` | HTMX partials (scan status, media table). |
| `POST /scan/tv`, `/scan/movies` | Kick off background threads that call `scan_library`. |
| `POST /settings` | Persist `Config` rows; reschedule APScheduler interval job when the interval changes. |
| `GET /posters/...` | Static JPEG thumbnails from disk. |

---

## Related files

| File | Responsibility |
|------|------------------|
| `main.py` | App factory, routes, static mount, scheduler lifecycle, config seeding. |
| `scanner.py` | Shallow scan, TMDB/TVDB clients, poster pipeline, background workers. |
| `database.py` | SQLite URL, session factory, `init_db()`. |
| `models.py` | SQLAlchemy ORM models. |

For user-facing setup, see the root **README.md**.
