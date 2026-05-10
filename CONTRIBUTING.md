# Contributing to Open Media Tracker

Thank you for helping improve Open Media Tracker. This document explains how we work together respectfully and how to set up a productive dev environment.

---

## Code of Conduct

We aim for a **professional, welcoming, and constructive** community.

- **Be respectful.** Critique ideas and code, not people. Assume good intent.
- **Stay on topic.** Keep discussions relevant to bugs, features, and documentation.
- **No harassment.** Unwelcome conduct—including discrimination, intimidation, or abuse—is not acceptable.
- **Collaborate openly.** Share context in issues and PRs so reviewers and future maintainers can follow along.

Maintainers may edit, close, or moderate discussions or contributions that undermine these standards.

---

## Development setup (without Docker)

From the repository root, using a virtual environment is strongly recommended.

### 1. Clone and create a venv

```bash
git clone https://github.com/YOUR_ORG/Open-Media-Tracker.git
cd Open-Media-Tracker
python -m venv .venv
```

### 2. Activate the venv

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

Edit `.env` with at least one TMDB credential and paths that exist on your machine.

### 5. Run the app

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8383
```

Visit **http://127.0.0.1:8383** (or set **`APP_PORT`** and match the `--port` value).

The SQLite database and poster cache default to `./data/` under the project directory unless `DATABASE_PATH` points elsewhere.

---

## Workflow

### Branching

- Create a **topic branch** off the default branch (e.g. `main`).
- Use a short, descriptive name: `fix/scanner-mtime-compare`, `feat/settings-validation`, `docs/readme-env-table`.

### Commits

Use **[Conventional Commits](https://www.conventionalcommits.org/)** style when possible:

| Prefix | Use for |
|--------|---------|
| `feat:` | New user-visible behavior |
| `fix:` | Bug fixes |
| `docs:` | Documentation only |
| `refactor:` | Internal change without behavior change |
| `test:` | Tests |
| `chore:` | Tooling, deps, formatting |

Examples:

```text
feat: surface TVDB login errors in scan panel
fix: skip invalid folder entries during scandir
docs: expand ARCHITECTURE shallow-scan section
```

### Pull requests

1. **Open an issue first** for larger changes (or reference an existing issue).
2. **Describe** what changed and **why**—link issues with `Fixes #123` when applicable.
3. **Keep PRs focused**—one logical change per PR is easier to review.
4. **Verify locally**: app starts, relevant scans/settings flows still work.
5. **Update docs** if behavior, env vars, or Docker usage changes.

Maintainers will review for correctness, clarity, and alignment with the project’s scope.

---

## Coding standards

### Python

- **PEP 8**–aligned layout and naming (4-space indent, `snake_case` functions, `PascalCase` classes).
- **Type hints** on public functions and non-trivial internals (`def foo(x: str) -> bool:`). Prefer modern annotations (`list[str]`, `X | None`).
- **Imports**: standard library first, then third party, then local modules; avoid unused imports.
- **Dependencies**: pin sensible minimum versions in `requirements.txt` when changing deps; keep the Docker image buildable.

### HTML / templates

- Match existing **Tailwind** utility patterns and dark-theme styling.
- Prefer **HTMX** attributes for progressive enhancement; avoid large inline scripts unless necessary.

### Scope

- Prefer **small, reviewable diffs** over drive-by refactors unrelated to the task.
- Do not commit secrets (`.env`, API keys). `.env.example` documents variables only.

---

## Questions?

Open a **GitHub issue** with the `question` label (or the closest equivalent). Clear reproduction steps and environment notes (OS, Python version, Docker vs. local) help everyone respond faster.

Again—thank you for contributing.
