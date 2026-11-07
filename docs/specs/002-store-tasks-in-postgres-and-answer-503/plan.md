---
spec_id: 002-store-tasks-in-postgres-and-answer-503
shape: service-python
spec_hash: ff4c75aa2a5d
summary: Tasks in Postgres via psycopg 3 (connection per call), 503 and not-ready while the database is unreachable
tasks:
  - id: t1
    title: Add the throwaway-Postgres test harness and the devbox postgresql package
    files: [devbox.json, tests/pg_harness.py, tests/conftest.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add psycopg and the Database module (timeouts, schema bootstrap, ping, StorageUnavailableError)
    files: [pyproject.toml, uv.lock, src/taskboard6_api/db.py, tests/test_db.py, docs/env-vars.md]
    covers: [AC-002.4, AC-002.5, AC-002.6, AC-002.7]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Add PostgresTaskStore and the TaskStorage seam
    files: [src/taskboard6_api/tasks/pg_store.py, src/taskboard6_api/tasks/store.py, src/taskboard6_api/tasks/api.py, tests/test_tasks_store.py, tests/test_pg_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.7]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t4
    title: Wire create_app, database readiness and the 503/500 handlers
    files: [src/taskboard6_api/main.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7]
    parallel_safe: false
    depends_on: [t3]
---

# Plan — 002 Store tasks in Postgres and answer 503 and not-ready while the database is unreachable

Contract, module interfaces and the test-harness fixtures: [design.md](design.md). Driver and connection strategy:
[ADR-001](../../adr/001-postgres-access-with-psycopg.md). No gitops task: the system plan's gitops-app PR
(`resource postgres`, `uses: postgres` on taskboard6-api) provides `DATABASE_URL`; the readiness probe is already
`/ready`.

## t1 — Add the throwaway-Postgres test harness and the devbox postgresql package

**Files:** devbox.json, tests/pg_harness.py, tests/conftest.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7 (enabler: every acceptance test of
this spec needs a real Postgres)
**Goal:** `devbox run test` (locally and in the template's CI `test` job) gets real, throwaway Postgres servers through
the fixtures named in design.md, without Docker and without a CI workflow change.

**Implementation notes:**
- `devbox.json`: add `"postgresql@16"` to `packages` only; do not touch the template's recipes.
- `tests/pg_harness.py`: a `PgServer` class (`url`, `port`, `start()`, `stop()`): `initdb -D <tmp>/data -U postgres
  -A trust --no-sync`, `pg_ctl -D ... -o "-c listen_addresses=127.0.0.1 -p <port> -k <tmp> -c fsync=off" -w start`,
  `pg_isready` wait, `pg_ctl -m fast stop`. Temp dirs under pytest's `tmp_path_factory`.
- Fixtures exactly as in design.md: `pg_url` (session; honours `TEST_DATABASE_URL`; sets and restores
  `os.environ["DATABASE_URL"]`), `clean_db` (`psql -c "TRUNCATE TABLE tasks RESTART IDENTITY"` only when
  `to_regclass('public.tasks')` is not null), `unreachable_url`, `pg_factory` (`free_port()`, `start(port=None)`,
  teardown stops and deletes every server it started).
- Binaries missing and no `TEST_DATABASE_URL`: `pytest.fail` with the message from design.md (never skip).
- Uses only the stdlib and `subprocess` + the PG binaries (no psycopg), so it does not depend on t2.
- `tests/conftest.py`: import the four fixtures from `pg_harness` (`# noqa: F401`); `client` now depends on `pg_url`
  and `clean_db` and returns `TestClient(app)`.
- Nothing starts at import or collection time; `devbox run smoke` must stay database-free.
- Stop every server at session end even when a test fails (finalizers), so CI leaves no `postgres` processes.

**Done when:** a throwaway test (not committed) can use each fixture; `devbox run test-fast` shows the existing tests
unchanged (the `/ready` test fails until t4, expected); `devbox run quality` is clean.

## t2 — Add psycopg and the Database module

**Files:** pyproject.toml, uv.lock, src/taskboard6_api/db.py, tests/test_db.py, docs/env-vars.md
**Covers:** AC-002.4, AC-002.5, AC-002.6, AC-002.7
**Goal:** one module that turns `DATABASE_URL` into short-lived connections with the spec's timeouts, creates the
schema on first success, answers readiness and maps every connectivity failure to `StorageUnavailableError`.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` to `dependencies`; refresh `uv.lock` through devbox (`devbox run`
  runs `uv sync --all-extras` in its init hook; never `uv add`/`pip`). The Dockerfile's `uv sync --locked` must pass.
- `Database(url: str | None = None)`; `_resolve_url()` returns `url` or `os.environ.get("DATABASE_URL")`; empty/None
  raises `StorageUnavailableError("DATABASE_URL is not set")`.
- `connection()` context manager: `psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=2000",
  keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=2)`; ensures the schema; yields; commits on
  success, rolls back on error; always closes. `psycopg.OperationalError` -> `raise StorageUnavailableError(<psycopg
  message>) from exc`.
- Schema DDL and advisory lock exactly as in design.md "Data"; per-instance flag behind a `threading.Lock`, set only
  after commit.
- `ping() -> bool`: own connection with `options="-c statement_timeout=1000"`, `SELECT 1`; any exception (including
  `StorageUnavailableError`) -> `False`, logged at `debug`. Does not ensure the schema.
- Never log or put the URL/conninfo into an exception message.
- `tests/test_db.py` (unit, no harness needed): unset/empty URL raises; a closed port (bind a socket, read its port,
  close it) raises `StorageUnavailableError` in under 3 s; `ping()` is `False` for both; message contains no password
  for a URL with `user:secret@`.
- `docs/env-vars.md`: a "Storage" section with `DATABASE_URL` as in design.md "Configuration".

**Done when:** `tests/test_db.py` passes and `devbox run quality` and `devbox run security` are clean (pip-audit on the
new dependency).

## t3 — Add PostgresTaskStore and the TaskStorage seam

**Files:** src/taskboard6_api/tasks/pg_store.py, src/taskboard6_api/tasks/store.py, src/taskboard6_api/tasks/api.py, tests/test_tasks_store.py, tests/test_pg_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.7
**Goal:** a durable store with the in-memory store's interface, and routes that depend on the protocol, not a class.

**Implementation notes:**
- `pg_store.py`: `PostgresTaskStore(db: Database)`; `add` and `list` with the SQL in design.md "Data", each in one
  `db.connection()`; build `Task` from the returned row (`created_at` is tz-aware from psycopg; the existing serializer
  converts to UTC `Z`).
- `store.py`: add `TaskStorage(Protocol)` with `add` and `list`; keep the in-memory `TaskStore` class byte-for-byte in
  behaviour (spec 001's acceptance tests instantiate it); replace the module-level `_store` singleton with
  `get_task_store(request: Request) -> TaskStorage` returning `request.app.state.task_store`.
- `api.py`: `StoreDep = Annotated[TaskStorage, Depends(get_task_store)]`; route bodies unchanged. No try/except in the
  routes: `StorageUnavailableError` propagates to the app handler (t4).
- `tests/test_tasks_store.py`: replace `test_get_task_store_is_singleton` (the singleton is gone) with a test that
  `get_task_store` returns `request.app.state.task_store`; keep every other test.
- `tests/test_pg_store.py` (unit, with `pg_url` + `clean_db`): order across three adds; microsecond `created_at`
  round-trip; table created on a fresh `pg_factory` server; a second `PostgresTaskStore(Database(url))` sees the same
  rows; closed port raises `StorageUnavailableError` and stores nothing.

**Done when:** `tests/test_pg_store.py` and `tests/test_tasks_store.py` pass; spec 001's `tests/test_tasks.py` still
passes; `devbox run quality` is clean.

## t4 — Wire create_app, database readiness and the 503/500 handlers

**Files:** src/taskboard6_api/main.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7
**Goal:** the HTTP surface of design.md: an app factory, `/ready` backed by the database, `503` for storage failures,
JSON `500` for anything else.

**Implementation notes:**
- `create_app(database_url: str | None = None) -> FastAPI`: builds the app, adds `MetricsMiddleware`, includes
  `tasks.router`, registers `/health`, `/ready`, `/ping`, `/metrics`, sets `app.state.database = Database(database_url)`
  and `app.state.task_store = PostgresTaskStore(app.state.database)`. `app = create_app()` at module level.
  `configure_logging` / `configure_tracing` stay at module import (once per process), not inside the factory.
- No database access at import or startup (no lifespan connect).
- `/ready`: `request.app.state.database.ping()` -> `200 {"status": "ready"}` or `JSONResponse(503, {"status": "not
  ready"})`. `/health` unchanged.
- `@app.exception_handler(StorageUnavailableError)` -> `JSONResponse(503, {"detail": "Task storage is unavailable"})`,
  logging `task_storage_unavailable` at `warning` with `error_type` (class of `exc.__cause__`, else of `exc`) and
  `error=str(exc)`; never the URL.
- `@app.exception_handler(Exception)` -> `JSONResponse(500, {"detail": "Internal Server Error"})`; the metrics tests
  (`tests/test_metrics.py`, `/boom` -> 500 counted) must keep passing.
- Keep sync handlers; keep the Dockerfile `CMD` (`taskboard6_api.main:app`) valid.

**Done when:** every acceptance test for AC-002.1 to AC-002.7 passes, spec 001's tests and the health/metrics tests
still pass, and `devbox run ci` is green.
