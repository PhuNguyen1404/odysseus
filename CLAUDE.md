# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Odysseus is a self-hosted AI workspace (chat + agents, deep research, documents, email, notes/tasks/calendar, model cookbook). Backend is a single-process FastAPI app (Python 3.11+); frontend is vanilla native ES modules served from `static/` (no bundler, no framework). License AGPL-3.0-or-later.

- `dev` is the default/integration branch and the target for all PRs; `main` is the curated release branch.
- Commits use Conventional Commits: `type(scope): summary` (e.g. `fix(search): ...`).
- Native Windows is not actively tested; Docker or Linux/macOS is the reference environment.

## Commands

```bash
# Run (Docker, UI on :7011; first admin password is in `docker compose logs odysseus`)
cp .env.example .env
docker compose up -d --build

# Run (manual dev)
pip install -r requirements.txt          # requirements-dev.txt adds test tooling (xdist etc.)
python -m uvicorn app:app --host 127.0.0.1 --port 7000

# Python checks
python -m compileall -q app.py core routes src services scripts tests
python -m pytest                                   # full suite (serial)
python -m pytest tests/test_foo.py::test_bar       # single test
python -m pytest -m area_security                  # taxonomy slice
python -m pytest -m "area_services and sub_cookbook"
python tests/run_focus.py --area services --fast   # focused runner (validates area names)
python -m pytest -q --shard 1/4                    # CI shard
python -m pytest -q -n 4 -p no:cacheprovider --max-worker-restart=0   # parallel, opt-in

# Frontend checks (need `npm ci`)
python scripts/build_frontend.py --check           # source/output byte parity
python scripts/build_frontend.py                   # publish frontend/src -> static/js
node scripts/check_frontend.mjs                    # architecture/import-boundary gate
node scripts/check_document_references.mjs
node --check static/js/<file>.js
node --test tests/frontendArchitecture.test.mjs tests/documentReferences.test.mjs
npm run test:photo-editor / npm run test:ios-layout   # Playwright e2e

# CSS cascade snapshot (any CSS move must keep the digest)
python scripts/css_snapshot.py --check

# Release smoke suite against a real booted instance
scripts/odysseus-smoke
```

Test notes:
- Tests are auto-tagged at collection with `area_*` / `sub_*` markers derived from filenames (`tests/_taxonomy.py`, `tests/conftest.py`). Read `tests/TESTING_STANDARD.md` before adding or moving tests.
- `tests/KNOWN_FAILURES.md` lists expected failures; anything else is a regression.
- Setting `APP_PORT` makes live smoke tests (marked `serial`) target an external instance — they must run with `-n 0`. Unset it for ordinary runs; otherwise those tests skip.
- Node tests (`*.test.mjs`) are not collected by pytest; run them with `node --test`.
- Only mark tests `slow` with `--durations` evidence. Never weaken tests with `skip`/`xfail` to get green.

## Architecture

**Entry point.** `app.py` is a "slim orchestrator": it sets up logging, middleware (CORS, security headers/CSP, auth), constructs shared managers (session manager, RAG, memory, research handler, presets, skills, model discovery, ...) and mounts routers. Each router module exposes a `setup_*_routes(dependencies...)` factory that returns an `APIRouter`; dependencies are injected explicitly rather than imported as globals. `launcher.py` / `Odysseus.spec` / `build-windows-portable.ps1` / `build-macos-app.sh` are packaging wrappers around the same app.

**Layers.**
- `routes/` — HTTP layer, one module (or subpackage) per feature area.
- `src/` — the bulk of application logic: agent loop (`agent_loop.py`), chat processing, LLM client (`llm_core.py`), endpoint/model resolution, deep research, RAG/Chroma, memory, email/CalDAV, MCP management, containment/sandboxing, path confinement, owner identity.
  - `src/agent_runtime/` — authority, effects/effect log, resource ownership and path policy for agent execution ("Harness V2"; version in `HARNESS_VERSION`, design notes in `docs/runtime-decomposition/`).
  - `src/agent_tools/` and `src/tools/` — tool implementations exposed to the agent.
- `services/` — larger feature services (search, research, memory, TTS/STT, shell, skills, hwfit, ...).
- `core/` — DB (SQLAlchemy over SQLite at `<DATA_DIR>/app.db`, `core/database.py`), auth, middleware, session manager, atomic IO.
- `mcp_servers/` — built-in MCP servers (email, memory, RAG, image gen). `integrations/` holds Claude/Codex bridges; `companion/` is device pairing.

**Agent turns.** See `docs/AGENT_TURN_CONTRACT.md`: `src/turn_contract.py` classifies requested capabilities; `routes/chat_routes.py` freezes the offered tool set (toggles, privileges, incognito, etc.); the dispatcher still enforces runtime policy, owner scope and approvals — a contract is selection, not authorization. **`src/agent_loop.py` and closely related execution/authorization/orchestration/context contracts are currently frozen for unrelated changes while Harness V2 lands — coordinate before touching them.**

**Frontend.** `static/index.html` + `static/app.js` + ~400 legacy modules in `static/js/`, plus `static/sw.js` (service worker with `PRECACHE`/`PANEL_PRECACHE` arrays). Migrated code lives in `frontend/src/` (feature-first: `features/<name>/{domain,application,infrastructure,ui}`, `shared/`) and is published byte-for-byte to `static/js/` via the mapping in `frontend/modules.json` (ADR: `docs/frontend-architecture/ADR-001-source-and-deployment.md`). Rules:
- Edit the `frontend/src/` source for any mapped module, run `python scripts/build_frontend.py`, and commit source and output together — CI fails on drift.
- New output paths need LF rules in `.gitattributes` and an entry in the service worker precache arrays.
- No bare package imports, no browser imports of `frontend/src`, no new dependency cycles.

## Code conventions (enforced in review)

- **Paths:** never derive writable paths from `Path(__file__)`, hardcode `/app/...`, or use relative `"data/..."`. Use named constants from `src/constants.py` (`AUTH_FILE`, `SETTINGS_FILE`, `CHROMA_DIR`, ...); add a constant for new fixed paths. `DATA_DIR` (from `ODYSSEUS_DATA_DIR`) is only for dynamic per-owner paths. The source tree is read-only in Docker. Guard directory creation so failures degrade gracefully.
- **Loopback URLs:** never hardcode `http://localhost:7000`; use `internal_api_base()` from `src.constants`.
- **Constants:** `src/constants.py` is the single source of truth; `core/constants.py` is only a re-export shim.
- **UI:** reuse existing CSS tokens (`--red`, `--fg`, `--bg`, `--card`, `--border`, ...) and existing button/input/card classes; no Unicode emoji in UI or code (use inline SVG like `static/index.html`); keep `Fira Code` as primary font; dark mode is default, light mode goes through the theme system. Visual changes must be checked in the running app.
- **Scope:** one coherent change per PR; don't mix file moves with logic changes. Structural/modularization work is coordinated via issue #4071.
- **Security:** keep `AUTH_ENABLED=true` and `LOCALHOST_BYPASS=false` outside local dev; backend owner-scope checks are authoritative.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
