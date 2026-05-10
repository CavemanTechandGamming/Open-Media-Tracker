# Architecture — Open Media Tracker

This document is the **technical deep-dive** for maintainers and advanced operators: stack overview, **shallow scanner design** (including behavior on very large libraries), **thumbnail pipeline**, persistence, and external APIs.

---

## System overview

Open Media Tracker is a **single-process** web application:

| Layer | Technology | Role |
|-------|-------------|------|
| **HTTP / HTML** | **FastAPI** | Routes, dependency-injected DB sessions, JSON health endpoint, Jinja2-rendered pages. |
| **Interactivity** | **HTMX** | Partial page updates for scan progress and settings without a separate SPA build. |
| **Styling** | **Tailwind CSS** (CDN) | Utility-first layout in templates. |
| **Data** | **SQLite** + **SQLAlchemy 2.x** | `media`, `episodes`, `config` tables; `init_db()` creates schema on startup. |
| **Jobs** | **APScheduler** | Background interval job reuses the same scan routine as manual triggers. |
| **Configuration** | **pydantic-settings** (`settings.py`) | Validates and loads environment variables; startup checks TMDB + TVDB requirements before binding the server. |

### Lifespan and zero-touch initialization

On application startup (`main.py` lifespan):

1. **Credential validation** — logs clear errors and exits if TMDB (token or key) and `TVDB_API_KEY` are missing.
2. **`ensure_runtime_directories()`** — creates database parent directory, **`cache/posters/`**, and **`logs/`** under `CONFIG_PATH` or `./data/`.
3. **`init_db()`** — `Base.metadata.create_all()` against SQLite; **no manual migrations** in-tree (Alembic not used).
4. **`seed_defaults()`** — inserts missing `config` rows from the environment so the UI has sensible defaults.
5. **APScheduler** — registers the shallow full-library job at the configured interval.

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Browser   │────▶│   FastAPI    │────▶│ SQLite           │
│  HTMX +     │◀────│   Jinja2     │◀────│ media, episodes, │
│  Tailwind   │     └──────┬───────┘     │ config           │
└─────────────┘            │             └──────────────────┘
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
│  TMDB   │   │  TVDB   │
│  API v3 │   │  API v4 │
└─────────┘   └─────────┘
```

---

## Scanner logic: shallow passes and mtime gates

Design goal: remain usable on **10 TB+** libraries and **low-power** hosts by avoiding full-tree walks on every pass.

### 1. Top-level enumeration (`os.scandir`)

For each configured root (`LIBRARY_TV_PATH` / `LIBRARY_MOVIES_PATH`), the scanner opens the root with **`os.scandir()`** and considers **only immediate child directories** as separate titles (one TV series or one movie per folder). No recursive descent at this stage.

### 2. Modification-time gate

For each candidate folder, the code reads **`st_mtime`** (via `DirEntry.stat(follow_symlinks=False)`), normalized for stable comparison, and compares it to **`Media.folder_mtime`** in SQLite.

| Condition | Behavior |
|-----------|----------|
| Row exists, **mtime unchanged**, and **`last_api_sync`** is set | **Skip** TMDB/TVDB calls and **skip** recursive file enumeration for that folder on this pass. |
| New folder or **mtime changed** | Run full **refresh** path for that title (APIs + local file logic as below). |

This is the **shallow scan contract**: cost scales with **number of top-level folders** plus **folders that actually changed**, not with total file count on every run.

### 3. Work done when a folder is “dirty”

**Television**

1. TMDB TV search by sanitized folder name.
2. Show detail + external IDs; optional TVDB extended series for status cross-check.
3. Season JSON from TMDB to build the canonical episode list.
4. **`os.walk`** **only under that show’s folder** to collect video files and parse `SxxEyy` / `1x01`-style patterns into `(season, episode)` keys.
5. Replace `Episode` rows; update counts and errors; commit.

**Movies**

1. TMDB movie search + detail.
2. **`os.walk`** (or equivalent) under the movie folder to detect **any** supported video extension for “present” semantics.

### 4. Manual vs scheduled scans

HTTP **Scan TV** / **Scan Movies** handlers and **APScheduler** both call **`scan_library()`**. The **mtime gate** applies in every case, so scheduled runs stay cheap when nothing under a top-level folder has changed.

---

## Image pipeline (local thumbnails)

The UI references **stable URLs** under **`/posters/{media_id}.jpg`**, backed by **`StaticFiles`** on a directory resolved from settings:

| Mode | Filesystem path |
|------|------------------|
| Docker (`CONFIG_PATH=/config`) | `/config/cache/posters/{id}.jpg` |
| Local dev (no `CONFIG_PATH`) | `./data/cache/posters/{id}.jpg` |

**Flow**

1. After TMDB returns a **`poster_path`**, **`download_poster_thumbnail()`** in `scanner.py` fetches the image from TMDB’s CDN.
2. **Pillow** opens the image, converts to RGB, optionally **downscales** (max width ~220 px), and writes **JPEG** with moderate quality.
3. **`Media.poster_local`** stores the web path (`/posters/{id}.jpg`) for templates.

This keeps the dashboard **snappy** on slow links and avoids depending on TMDB’s image URLs at render time.

---

## Database schema (conceptual)

See **`models.py`** for exact columns.

### `media`

One row per **top-level library folder** that has been seen.

- **Identity:** `folder_path` (unique), `folder_name`, `media_type` (`tv` \| `movie`).
- **Sync:** `folder_mtime`, `last_api_sync`, `last_error`.
- **External IDs:** `tmdb_id`, `tvdb_id`.
- **Display:** `title`, `status`, `poster_local`.
- **TV aggregates:** `total_episodes_api`, `episodes_present_local`.

### `episodes`

Child rows for **TV** after a successful refresh: season/episode numbers, optional title, **`exists_locally`**.

### `config`

Key/value settings; **UI saves** override values initially **seeded from the environment**.

---

## External APIs

### TMDB (v3)

- Base URL `https://api.themoviedb.org/3`.
- Auth: **Bearer** (`TMDB_READ_ACCESS_TOKEN`) preferred, else **`api_key`** query parameter (`TMDB_API_KEY`).

### TVDB (v4)

- Login at `https://api4.thetvdb.com/v4/login` with `apikey` and optional **`pin`**.
- In current releases, **`TVDB_API_KEY` is required at application startup** (see `validate_api_credentials` in `settings.py`); the client is still optional inside individual scan paths when validating series status.

### Rate limiting (current behavior)

There is **no centralized rate limiter**. Load is reduced by design (mtime gate, mostly sequential requests per folder). Failures surface on **`Media.last_error`** and in scan UI fragments.

---

## HTTP surface (selected routes)

| Method / path | Purpose |
|---------------|---------|
| `GET /` | Redirects to **`/tv`**. |
| `GET /movies`, `GET /tv`, `GET /settings`, `GET /about` | Full pages or **HTMX** `#main-content` fragments when `HX-Request: true`. |
| `GET /tv/{id}/audit` | Missing-episode list for one show (reads `episodes` where `exists_locally` is false). |
| `GET /health` | `{"status":"ok"}` for Docker health checks and proxies. |
| `GET /fragments/movies-table`, `/fragments/tv-table` | HTMX table refresh. |
| `GET /fragments/scan-*-status` | Scan progress partials. |
| `POST /scan/tv`, `POST /scan/movies` | Start background scan threads. |
| `POST /settings` | Persist `config`; reschedule interval job when `SCAN_INTERVAL_MINUTES` changes. |
| `GET /posters/...` | Cached JPEG thumbnails. |

---

## Key source files

| File | Responsibility |
|------|----------------|
| `main.py` | FastAPI app, lifespan, routes, static mount, scheduler wiring, config seeding. |
| `scanner.py` | Shallow scan, TMDB/TVDB clients, poster download, background workers. |
| `settings.py` | Environment model, directory resolution, API validation. |
| `database.py` | SQLite URL, engine, `SessionLocal`, `init_db()`. |
| `models.py` | ORM models. |

User-facing installation: **[README.md](../README.md)**.
