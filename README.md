# Open Media Tracker

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-compose-ready-2496ED.svg)](docker-compose.yml)

**Self-host a lightweight dashboard that audits your TV and movie folders against TMDB (and optionally TVDB)—without hammering APIs or your disks.**

---

## Features

| Capability | What it does |
|------------|----------------|
| **Shallow scanning** | Walks only **top-level** library folders with `os.scandir()`. Compares each folder’s `st_mtime` to SQLite; **TMDB/TVDB and deeper file checks run only when the folder is new or changed.** |
| **Metadata integration** | Resolves titles, status (e.g. ended vs. returning), IDs, and episode lists via **TMDB**; optional **TVDB v4** login for an extra series-status signal when configured. |
| **Local poster cache** | Downloads posters and stores **resized JPEG thumbnails** under `data/cache/posters/` locally, or **`/config/cache/posters/`** when using Docker **`CONFIG_PATH=/config`**. No hotlinked CDN images in the browser. |
| **Independent scans** | **Scan TV** and **Scan Movies** are separate actions with **HTMX** progress panels (no full-page reload). |
| **Configurable schedules** | **APScheduler** runs periodic shallow passes; interval is configurable (minimum 15 minutes). |
| **In-app settings** | API keys and paths can be stored in SQLite after the first save (seeded from `.env` on a fresh install). |

---

## Tech stack

| Layer | Choice |
|-------|--------|
| **Backend** | Python 3.14, **FastAPI**, **Uvicorn** |
| **Frontend** | **HTMX** + **Tailwind CSS** (CDN) + Jinja2 templates |
| **Database** | **SQLite** via **SQLAlchemy** 2.x |
| **Jobs** | **APScheduler** (background interval scans) |
| **Container** | **Docker** & **Docker Compose** |

---

## Quick start (Docker Compose)

Designed to sit beside **Plex**, **Jellyfin**, **Pi-hole**, **OMV**, **Audiobookshelf**, etc.: the default HTTP port is **8383** (not 80, 443, 8000, 8080, 8096, or 32400). Change **`APP_PORT`** in `.env` if that port is taken—**no image rebuild** required.

From the repository root:

```bash
git clone https://github.com/YOUR_ORG/Open-Media-Tracker.git
cd Open-Media-Tracker
cp .env.example .env
```

Edit `.env`:

1. Set **`TV_PATH`** and **`MOVIE_PATH`** to **host** directories for your libraries (Compose bind-mounts them **read-only** into `/media/tv` and `/media/movies`). If you only use TV, point `MOVIE_PATH` at an empty folder on the host.
2. Set **either** `TMDB_READ_ACCESS_TOKEN` **or** `TMDB_API_KEY` (and optionally `TVDB_API_KEY`).
3. Optionally set **`APP_PORT`** (default `8383`) and **`APP_PUBLIC_HOST`** (shown in startup logs).

Start the stack:

```bash
docker compose up --build
```

On first boot the container logs **`Ready at http://localhost:8383`** (port follows **`APP_PORT`**).

Open **http://localhost:8383** in your browser unless you changed `APP_PORT`.

**Data layout:** A named Docker volume mounts **`/config`** inside the container for SQLite (`open_media_tracker.db`) and poster thumbnails under **`cache/posters/`**. Your media mounts are **`:ro`** so the app cannot modify library files.

### Run from Docker Hub (no `git clone` on the host)

Maintainers publish images with [GitHub Actions](.github/workflows/docker-publish.yml) after adding these **repository secrets**: **`DOCKERHUB_USERNAME`**, **`DOCKERHUB_TOKEN`** (create an access token under [Docker Hub → Account Settings → Security](https://hub.docker.com/settings/security)).

| Trigger | What gets pushed |
|---------|-------------------|
| **Git tag** `v1.2.3` | `youruser/open-media-tracker:1.2.3`, `1.2`, and **`latest`** (linux/amd64 + linux/arm64) |
| **Actions → Publish Docker image → Run workflow** | Tag you type (default **`edge`**) — use when you want a one-off build without a semver tag |

**On any machine** you only need a `.env` (from [.env.example](.env.example)) and Compose:

1. Clone **once** (or copy only `docker-compose.yml` + `.env.example`), set `DOCKER_IMAGE=YOURDOCKERHUB/open-media-tracker:latest` in `.env`, fill API keys and `TV_PATH` / `MOVIE_PATH`.
2. Run:

   ```bash
   docker compose pull
   docker compose up -d --no-build
   ```

`--no-build` skips a local image build and uses the pulled image. Omit `--no-build` when you are developing with `build: .` and leave `DOCKER_IMAGE` unset or equal to the local image name.

First pull:

```bash
docker pull YOURDOCKERHUB/open-media-tracker:latest
```

---

## Configuration

Environment variables seed the database **once** for missing keys. Values changed in the **Settings** section of the web UI are persisted in SQLite and override env defaults for that key thereafter.

| Variable | Required | Description |
|----------|----------|-------------|
| `TMDB_READ_ACCESS_TOKEN` | One of TMDB auth\* | TMDB **Bearer** read access token from [API settings](https://www.themoviedb.org/settings/api). **Preferred** if both TMDB variables are set. |
| `TMDB_API_KEY` | One of TMDB auth\* | Classic TMDB **v3 API key** (query parameter). Use if you do not use a read access token. |
| `TVDB_API_KEY` | No | TVDB **v4** API key ([account](https://thetvdb.com/dashboard/account/apikey)). Enables optional series status cross-check. |
| `TVDB_PIN` | No | Subscriber PIN for TVDB login, **only** if your TVDB setup requires it; sent with the login payload when non-empty. |
| `APP_PORT` | No | Uvicorn listen port (default **`8383`**). Docker Compose maps host→container using this value. |
| `APP_PUBLIC_HOST` | No | Hostname printed in startup logs (default `localhost`). Does not change binding; use for clarity on LAN installs. |
| `CONFIG_PATH` | No | When set (Compose uses **`/config`**), SQLite defaults to **`$CONFIG_PATH/open_media_tracker.db`** and posters to **`$CONFIG_PATH/cache/posters/`**. Local dev leaves this unset (`./data/` under the app). |
| `DOCKER_IMAGE` | Compose | **Docker Hub image** (e.g. `youruser/open-media-tracker:latest`). Set in `.env` when using **`docker compose pull`** instead of building locally. |
| `TV_PATH` / `MOVIE_PATH` | Compose | **Host paths** passed into `docker-compose.yml` for **read-only** bind mounts at `/media/tv` and `/media/movies`. |
| `LIBRARY_TV_PATH` | Recommended | Path seen **inside the running app** to the TV root. Compose pins **`/media/tv`**; override only if you customize mounts. |
| `LIBRARY_MOVIES_PATH` | Recommended | Path seen **inside the running app** to the movies root. Compose pins **`/media/movies`**. |
| `SCAN_INTERVAL_MINUTES` | No | Background shallow-scan interval in minutes (default `360`; app enforces a **minimum of 15**). |
| `DATABASE_PATH` | No | Optional explicit SQLite file path; overrides the `CONFIG_PATH` default when set. |

\*You must configure **at least one** of `TMDB_READ_ACCESS_TOKEN` or `TMDB_API_KEY`.

### Security notes for publishing this repo

- Never commit **`.env`** or SQLite files; **`.gitignore`** excludes them. Use **`.env.example`** only for empty templates.
- Prefer **read-only** Docker binds for library roots (already set in `docker-compose.yml`).
- Dependency versions are **pinned** in `requirements.txt` to reduce surprise upgrades in production.

---

## Usage

### Web UI

- **Library table**: Alphabetical overview of indexed TV and movies with status badges, TMDB/TVDB IDs, **missing episode counts** (TV), and locally cached thumbnails.
- **Scan TV / Scan Movies**: Triggers a shallow pass for that library type. Progress bars update via HTMX polling.
- **Settings**: Update paths, TMDB/TVDB credentials, and scan interval. Saving replaces the page body via HTMX.

### Manual vs. periodic scans

| Mode | Behavior |
|------|-----------|
| **Manual** | Click **Scan TV** or **Scan Movies**. Only folders whose **mtime** changed (or are new) trigger API work and local episode enumeration for TV. |
| **Periodic** | APScheduler runs on the interval from `SCAN_INTERVAL_MINUTES` (or the value saved in Settings). The same shallow + mtime rules apply—**unchanged folders are skipped** for metadata refresh. |

---

## Project layout

```
Open-Media-Tracker/
├── main.py              # FastAPI app, routes, scheduler wiring
├── scanner.py           # Shallow scan, TMDB/TVDB, posters
├── models.py            # SQLAlchemy models
├── database.py          # Engine & sessions
├── templates/           # Jinja + HTMX UI
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── docs/
    └── ARCHITECTURE.md  # Internal design notes
```

---

## Roadmap

Ideas for future releases (not commitments):

- **Notifications**: webhook or email when new seasons end, missing episodes spike, or scans fail.
- **Authentication**: optional login / API tokens for multi-user or internet-exposed installs.
- **Smarter matching**: alternate title sources, manual TMDB/TVDB ID override per folder.
- **Rate-limit hygiene**: configurable backoff, concurrency caps, and honor `Retry-After` where providers send it.
- **Tests**: pytest suite for scanner logic and HTTP boundaries.

Contributions are welcome—see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

This project is licensed under the **MIT License**—see [LICENSE](LICENSE).
