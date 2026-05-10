# Open Media Tracker

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Docker Ready](https://img.shields.io/badge/docker-ready-2496ED?logo=docker)](https://docs.docker.com/get-docker/)

**Open Media Tracker** is a self-hosted, **Docker-first** dashboard for auditing **TV** and **movie** libraries against **TMDB** and **TVDB**. It targets homelab and low-power hardware: **shallow scanning** (top-level folders + mtime gates) keeps disk and API load predictable on very large collections.

---

## Requirements

| Requirement | Notes |
|-------------|--------|
| **Docker** | Recommended: Docker Engine **24+** with Compose V2, or **Docker Desktop**. |
| **Python** | **3.14** if you run from source (see [CONTRIBUTING.md](CONTRIBUTING.md)). |
| **APIs** | **TMDB**: `TMDB_READ_ACCESS_TOKEN` *or* `TMDB_API_KEY`. **TVDB**: `TVDB_API_KEY` is **required** at startup in current releases. |

### Known limitations — local storage only

**The application is designed and tested for libraries on the host’s local filesystem** (paths you bind-mount into the container, or local paths when running without Docker).

**NAS, SMB/CIFS, mapped network drives, and similar remote storage are not supported** in this release. Bind mounts that rely on Windows letter-mapped shares or opaque network paths often appear empty or inconsistent inside the container and are **out of scope** for bug reports until first-class remote support exists.

If you need network-backed media today, sync or mount that content to a **local directory** the container can see as a normal folder, then point `TV_PATH` / `MOVIE_PATH` there.

---

## Features

| Capability | Description |
|------------|-------------|
| **Shallow scanning** | Uses **`os.scandir()`** on each library root only. Compares each title folder’s **`st_mtime`** to SQLite; **TMDB/TVDB work and deep file walks run only when that folder is new or changed.** |
| **Metadata** | TMDB for search, details, seasons, and posters; TVDB v4 for login and optional series-status cross-check when credentials are present. |
| **Independent audits** | **Scan TV** and **Scan Movies** are separate actions with **HTMX** progress fragments. |
| **Scheduled passes** | **APScheduler** runs the same shallow logic on an interval (minimum **15** minutes). |
| **Zero-touch startup** | On first boot the app **creates** the SQLite file and **all tables** (`Base.metadata.create_all`), **creates** cache/log directories under `CONFIG_PATH` (or `./data/` in dev), and **seeds** `config` from the environment. No manual database steps. |
| **Poster pipeline** | Posters are downloaded once, resized to JPEG, and served from **`/posters`** so the UI stays fast without hotlinking TMDB CDN URLs in the browser. |

---

## Quick start (Docker — recommended)

Default HTTP port is **8383** (avoids common conflicts with Plex, Jellyfin, Pi-hole, etc.). Override with **`APP_PORT`** in `.env` without rebuilding the image.

### 1. Create a project directory and `.env`

On the host, create a folder (for example `open-media-tracker`) and a **`.env`** file. Copy variable names from [.env.example](.env.example) and set at least:

- `DOCKER_IMAGE` — your image on Docker Hub, e.g. `youruser/open-media-tracker:latest`
- `TV_PATH`, `MOVIE_PATH` — **local** host paths to library roots (read-only in Compose)
- `TMDB_READ_ACCESS_TOKEN` **or** `TMDB_API_KEY`
- `TVDB_API_KEY`

### 2. Add `docker-compose.yml`

Save the following next to `.env` (same directory):

```yaml
name: open-media-tracker

networks:
  open-media-tracker:
    driver: bridge

services:
  open-media-tracker:
    image: ${DOCKER_IMAGE:?Set DOCKER_IMAGE in .env}
    container_name: open-media-tracker
    pull_policy: always
    restart: unless-stopped
    networks:
      - open-media-tracker
    ports:
      - "${APP_PORT:-8383}:${APP_PORT:-8383}"
    env_file:
      - .env
    environment:
      APP_PORT: ${APP_PORT:-8383}
      CONFIG_PATH: /config
      LIBRARY_TV_PATH: /media/tv
      LIBRARY_MOVIES_PATH: /media/movies
      TMDB_API_KEY: ${TMDB_API_KEY:-}
      TMDB_READ_ACCESS_TOKEN: ${TMDB_READ_ACCESS_TOKEN:-}
      TVDB_API_KEY: ${TVDB_API_KEY:-}
      TVDB_PIN: ${TVDB_PIN:-}
    volumes:
      - open-media-tracker-config:/config
      - ${TV_PATH:?Set TV_PATH in .env}:/media/tv:ro
      - ${MOVIE_PATH:?Set MOVIE_PATH in .env}:/media/movies:ro
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('APP_PORT','8383')+'/health')",
        ]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 25s

volumes:
  open-media-tracker-config:
```

### 3. Start

```bash
docker compose up -d
```

On success, logs include **`Ready at http://localhost:8383`** (port reflects **`APP_PORT`**). Open that URL in a browser.

**Persistence:** A named volume holds **`/config`** (SQLite at `open_media_tracker.db`, thumbnails under `cache/posters/`, logs under `logs/`). Library bind mounts are **`:ro`**.

### Alternative: clone and build from source

For development or private builds, clone the repository and use the root [`docker-compose.yml`](docker-compose.yml) with `docker compose up --build`, or run **uvicorn** locally — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Configuration reference

Variables are read from the environment (and optional **`.env`** file) via **pydantic-settings**. Values saved in the **Settings** UI are stored in SQLite and override env defaults for the same keys.

| Variable | Required | Description |
|----------|----------|-------------|
| `TMDB_READ_ACCESS_TOKEN` | One of TMDB\* | TMDB **Bearer** read access token ([API settings](https://www.themoviedb.org/settings/api)). Used in preference to the API key when both are set. |
| `TMDB_API_KEY` | One of TMDB\* | TMDB **v3 API key** (query parameter). |
| `TVDB_API_KEY` | **Yes** | TVDB **v4** API key ([TheTVDB account](https://thetvdb.com/dashboard/account/apikey)). Required for application startup in current images. |
| `TVDB_PIN` | No | TVDB subscriber **PIN**, only if your account requires it for login. |
| `APP_PORT` | No | HTTP listen port (default **8383**). Compose maps host↔container using this value. |
| `APP_PUBLIC_HOST` | No | Informational hostname in logs (default `localhost`); does not change bind address. |
| `CONFIG_PATH` | No | Writable app data root. Compose typically sets **`/config`**. SQLite defaults to `$CONFIG_PATH/open_media_tracker.db`; thumbnails to `$CONFIG_PATH/cache/posters/`; logs to `$CONFIG_PATH/logs/`. Unset locally → `./data/` under the app. |
| `DATABASE_PATH` | No | Explicit SQLite file path; overrides the `CONFIG_PATH`-derived default when set. |
| `LIBRARY_TV_PATH` | No | Path **inside** the running process to the TV root. Compose pins **`/media/tv`**. |
| `LIBRARY_MOVIES_PATH` | No | Path **inside** the process to the movies root. Compose pins **`/media/movies`**. |
| `SCAN_INTERVAL_MINUTES` | No | Background scan interval in minutes (default **360**; minimum **15** enforced). |
| `SQL_ECHO` | No | Set to `true` / `1` / `yes` to echo SQL to logs (debug). |

**Docker Compose–only** (not read by `settings.py`; used for orchestration):

| Variable | Required | Description |
|----------|----------|-------------|
| `DOCKER_IMAGE` | For Hub pulls | Full image reference, e.g. `youruser/open-media-tracker:latest`. |
| `TV_PATH` | Yes (Compose file) | **Host** path bound read-only to `/media/tv`. |
| `MOVIE_PATH` | Yes (Compose file) | **Host** path bound read-only to `/media/movies`. |

\*Configure **at least one** of `TMDB_READ_ACCESS_TOKEN` or `TMDB_API_KEY`.

---

## Usage

| Area | Behavior |
|------|----------|
| **Dashboard** | Table of indexed titles, status, IDs, missing-episode counts (TV), cached posters. |
| **Scan TV / Scan Movies** | Background shallow pass; HTMX polls status fragments. |
| **Settings** | Updates persisted `config` keys; changing the scan interval reschedules APScheduler. |

---

## Publishing & CI

Maintainers can push multi-arch images (**linux/amd64**, **linux/arm64**) with [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) after configuring GitHub Actions secrets **`DOCKERHUB_USERNAME`** and **`DOCKERHUB_TOKEN`**. See [CONTRIBUTING.md](CONTRIBUTING.md#publishing-docker-images-docker-hub).

---

## Project layout

```text
Open-Media-Tracker/
├── main.py              # FastAPI app, lifespan, routes, scheduler
├── scanner.py           # Shallow scan, TMDB/TVDB, posters
├── settings.py          # Environment configuration (pydantic-settings)
├── database.py          # SQLite engine, sessions, init_db()
├── models.py            # SQLAlchemy models
├── templates/           # Jinja2 + HTMX
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── docs/
    └── ARCHITECTURE.md
```

---

## Roadmap (non-binding)

- First-class **remote / NAS** library support and clearer mount guidance.
- **Authentication** for exposed installs.
- **Notifications** (webhook / email) for scan failures or catalog drift.
- **Tests** (pytest) for scanner and HTTP boundaries.

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE).
