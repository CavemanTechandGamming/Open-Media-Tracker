# Contributing to Open Media Tracker

Thank you for helping improve Open Media Tracker. This document describes community expectations, **development workflow**, **issue reporting**, and how maintainers publish Docker images.

---

## Code of conduct

We aim for a **professional, welcoming, and constructive** community.

- **Be respectful.** Critique ideas and code, not people. Assume good intent.
- **Stay on topic.** Keep discussions relevant to bugs, features, and documentation.
- **No harassment.** Unwelcome conduct—including discrimination, intimidation, or abuse—is not acceptable.
- **Collaborate openly.** Share context in issues and pull requests so reviewers and future maintainers can follow along.

Maintainers may edit, close, or moderate discussions or contributions that undermine these standards.

---

## Reporting issues and suggesting features

### Before you open an issue

1. **Read the README** (especially **Known limitations — local storage only**) and **[KNOWN_ISSUES.md](KNOWN_ISSUES.md)**. Problems caused by **NAS-only paths, SMB-only mounts, or mapped network drives** are documented as **unsupported** today; opening an issue is still welcome as a **feature request**, but it may be labeled accordingly rather than treated as a defect.
2. **Search existing issues** for duplicates.
3. **Reproduce** on the latest **Docker image** or on a clean **local dev** setup (see below).

### Bug reports

Include:

| Item | Why it helps |
|------|----------------|
| **OS and Docker** | e.g. Windows 10 + Docker Desktop 4.x, or Ubuntu 22.04 + Engine 24.x |
| **Image tag** | e.g. `youruser/open-media-tracker:latest` digest or semver tag |
| **Compose / run command** | How you start the container |
| **Relevant `.env` keys** | Redact secrets; show whether paths are local disks vs network |
| **Logs** | `docker compose logs` (or console output for `uvicorn`) around failure |
| **Expected vs actual** | Short, concrete description |

### Feature requests

Describe the **user problem**, proposed **behavior**, and any **constraints** (performance, security, compatibility). Example: *“Support library roots on SMB when Docker can reliably stat mtime”* — link to prior discussion if any.

---

## Development setup (dev mode)

End users should prefer **Docker** ([README.md](README.md)). Contributors typically run **FastAPI in reload mode** from a virtual environment.

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/YOUR_ORG/Open-Media-Tracker.git
cd Open-Media-Tracker
python -m venv .venv
```

### 2. Activate the virtual environment

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit **`.env`**: set **at least one** TMDB credential, **`TVDB_API_KEY`**, and **local** `LIBRARY_TV_PATH` / `LIBRARY_MOVIES_PATH` (or rely on Compose-style paths if you mirror production).

### 5. Run the application (dev mode)

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8383
```

Open **http://127.0.0.1:8383**. The app creates **`./data/`** (SQLite, `cache/posters/`, `logs/`) on first successful startup when `CONFIG_PATH` is unset.

---

## Git workflow

### Branching

- Branch from **`main`** (or the default branch).
- Use short, descriptive names: `fix/scanner-mtime`, `feat/docker-healthcheck`, `docs/readme-docker-first`.

### Commit messages

Use **[Conventional Commits](https://www.conventionalcommits.org/)** prefixes so history and changelogs stay scannable:

| Prefix | Use for |
|--------|---------|
| `feat:` | New user-visible behavior |
| `fix:` | Bug fixes |
| `docs:` | Documentation only |
| `refactor:` | Internal change without intended behavior change |
| `test:` | Tests |
| `chore:` | Tooling, dependencies, CI, formatting |

Examples:

```text
feat: add optional pull_policy for compose service
fix: handle missing TVDB token in scheduled scan
docs: document local-only storage limitation
```

### Pull requests

1. Prefer **one logical change** per PR.
2. **Describe** what changed and **why**; link issues with `Fixes #123` when applicable.
3. **Run the app** locally (or in Docker) and exercise affected flows.
4. **Update documentation** when behavior, environment variables, or Docker usage changes.

---

## Publishing Docker images (Docker Hub)

The workflow [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) builds **linux/amd64** and **linux/arm64** and pushes to Docker Hub.

1. Add GitHub Actions secrets **`DOCKERHUB_USERNAME`** and **`DOCKERHUB_TOKEN`** ([Docker Hub access token](https://hub.docker.com/settings/security)).
2. Ensure the Hub repository name matches **`IMAGE_NAME`** in the workflow (default **`open-media-tracker`**).
3. **Release:** push a semver tag such as **`v1.0.0`**; the workflow publishes version tags and **`latest`**.
4. **Ad hoc:** **Actions → Publish Docker image → Run workflow**; default tag **`edge`** avoids overwriting **`latest`** unless you change the input.

---

## Coding standards

### Python

- **PEP 8**–aligned layout (4-space indent, `snake_case` functions, `PascalCase` classes).
- **Type hints** on public APIs and non-trivial internals.
- **Imports:** standard library, third party, then local modules.
- **Dependencies:** pin versions in **`requirements.txt`** when adding or changing packages.

### Templates

- Follow existing **Tailwind** and **HTMX** patterns; avoid large inline scripts unless necessary.

### Scope and secrets

- Prefer **small, reviewable diffs**.
- Never commit **`.env`**, API keys, or database files. **`.env.example`** documents names and intent only.

---

## Questions

Open a **GitHub issue** with clear context (OS, Docker vs local, image tag). Thank you for contributing.
