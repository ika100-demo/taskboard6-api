# Design — 002 Store tasks in Postgres and answer 503 and not-ready while the database is unreachable

## Decisions

- **psycopg 3, one connection per store call, schema created in code** ([ADR-001](../../adr/001-postgres-access-with-psycopg.md)).
  Every call opens `psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=2000")` and closes it.
  Nothing is held between requests, so a database that comes back is used by the very next request (AC-002.7) and
  there is no stale pooled connection to discard. No `psycopg_pool` (its backoff makes recovery time unpredictable).
- **The TaskStore seam stays.** Routes depend on `get_task_store`; it now returns the app's `PostgresTaskStore`. The
  in-memory `TaskStore` class stays unchanged as a test double (spec 001's acceptance tests override the dependency
  with it). A `TaskStorage` `Protocol` (`add`, `list`) types the dependency.
- **App factory.** `main.create_app(database_url: str | None = None) -> FastAPI`; `app = create_app()` stays the
  module-level ASGI app (Dockerfile `CMD` unchanged). `database_url=None` means "read `DATABASE_URL` from the
  environment on every connect", so the module app works when tests set the variable after import. Each app holds its
  own `Database` and `PostgresTaskStore` on `app.state`; a second `create_app(url)` is "a restarted service" or "a
  second process" for in-process tests (AC-002.1, AC-002.2).
- **One domain error.** `StorageUnavailableError` (in `db.py`) is raised for any `psycopg.OperationalError` and for a
  missing/empty `DATABASE_URL`. One exception handler maps it to `503` and logs it (AC-002.4, AC-002.5). Inserts run in
  one transaction, so a failure creates nothing (AC-002.4).
- **Unexpected errors are JSON.** A handler for `Exception` answers `500 {"detail": "Internal Server Error"}` (system
  Errors section); the metrics middleware still counts the 500 and the error type.
- **Startup never touches the database.** No lifespan connect, no import-time connect: the process starts and `/health`
  is green with the database down or `DATABASE_URL` unset (AC-002.6, AC-002.7).
- **Tests use a real, throwaway Postgres started from the devbox `postgresql` package** (`initdb` + `pg_ctl` into a
  temp dir, `127.0.0.1`, trust auth) by a fixture module in `tests/`. No Docker needed, so it works the same on a
  laptop, GitHub-hosted and self-hosted runners, and the template-owned `test` job in `ci.yml` (`devbox run test`) gets
  Postgres without a CI change. `TEST_DATABASE_URL`, when set, replaces the session server (for a Postgres you run
  yourself); tests that need to start/stop a server still use their own throwaway one.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `taskboard6_api/db.py` | `Database` (connect with timeouts, ensure schema once, `ping`), `StorageUnavailableError` | new |
| `taskboard6_api/tasks/pg_store.py` | `PostgresTaskStore` (`add`, `list`) on a `Database` | new |
| `taskboard6_api/tasks/store.py` | `TaskStorage` protocol; in-memory `TaskStore` unchanged; `get_task_store(request)` returns `request.app.state.task_store` | changed |
| `taskboard6_api/tasks/api.py` | `StoreDep` typed with `TaskStorage`; routes unchanged | changed |
| `taskboard6_api/main.py` | `create_app`, `/ready` checks the database, 503 and 500 handlers | changed |
| `tests/pg_harness.py` | throwaway Postgres servers and fixtures (below) | new |
| `tests/conftest.py` | exposes the harness fixtures; `client` fixture uses the test database | changed |
| `devbox.json` | adds package `postgresql@16` (`initdb`, `pg_ctl`, `psql`, `pg_isready`) | changed |
| `pyproject.toml`, `uv.lock` | adds `psycopg[binary]>=3.2` | changed |

Public Python interface (tests may rely on it):

```python
# db.py
class StorageUnavailableError(Exception): ...           # str() never contains the password
class Database:
    def __init__(self, url: str | None = None) -> None: ...   # None: os.environ["DATABASE_URL"] at each connect
    def connection(self) -> ContextManager[psycopg.Connection]: ...  # timeouts set, schema ensured; raises StorageUnavailableError
    def ping(self) -> bool: ...                          # SELECT 1, statement_timeout 1 s; never raises

# tasks/pg_store.py
class PostgresTaskStore:
    def __init__(self, db: Database) -> None: ...
    def add(self, title: str, due_date: date | None) -> Task: ...   # raises StorageUnavailableError
    def list(self) -> list[Task]: ...                               # ORDER BY seq; raises StorageUnavailableError

# tasks/store.py
class TaskStorage(Protocol):
    def add(self, title: str, due_date: date | None) -> Task: ...
    def list(self) -> list[Task]: ...
class TaskStore: ...                                     # in-memory, unchanged (test double)
def get_task_store(request: Request) -> TaskStorage: ... # request.app.state.task_store

# main.py
def create_app(database_url: str | None = None) -> FastAPI: ...
app: FastAPI                                             # = create_app()
```

## Contract

Spec 001's contract (fields, trimming, 1 to 200 character titles, strict `YYYY-MM-DD`, FastAPI 422 shape, creation
order, exactly four keys per Task) is unchanged (AC-002.3). This spec adds:

### Task (unchanged, now durable)

`{"id": "<uuid4>", "title": str, "due_date": "YYYY-MM-DD" | null, "created_at": "YYYY-MM-DDTHH:MM:SS.ffffffZ"}`.
`created_at` round-trips through `timestamptz` with microsecond precision, so `GET /tasks` after a restart returns the
exact strings `POST /tasks` returned (AC-002.1).

### `POST /tasks`

- `201` the created Task (unchanged).
- `422` FastAPI validation error (unchanged; validation runs before the database is touched, so an invalid body is
  `422` even while the database is down).
- `503` `{"detail": "Task storage is unavailable"}`, `Content-Type: application/json`, when the database cannot be
  reached, a statement times out, or `DATABASE_URL` is unset/empty. Nothing is stored. Answered within 5 s (connect
  timeout 2 s + statement timeout 2 s) (AC-002.4).

### `GET /tasks`

- `200` JSON array of Task ordered by insertion (`ORDER BY seq`), shared by every process on the same database
  (AC-002.1, AC-002.2).
- `503` `{"detail": "Task storage is unavailable"}` as above (AC-002.5).

### `GET /ready`

- `200` `{"status": "ready"}` when `SELECT 1` succeeds.
- `503` `{"status": "not ready"}` when `DATABASE_URL` is unset/empty, the connect fails, or the query does not answer
  within 1 s (`statement_timeout=1000`; the connect is bounded by libpq's 2 s minimum `connect_timeout`) (AC-002.6,
  AC-002.7). Never raises, never logs above `debug` (probes run every few seconds).

### `GET /health`

`200` `{"status": "ok"}` always; never touches the database (AC-002.6).

### Unexpected errors

`500` `{"detail": "Internal Server Error"}` (JSON) for any unhandled exception.

### Logs

Every 503 of a task route logs one structlog event at `warning`: `event="task_storage_unavailable"`,
`error_type=<exception class of the cause>`, `error=<psycopg message>`. Never `DATABASE_URL`, `PGPASSWORD` or any
conninfo string; `StorageUnavailableError("DATABASE_URL is not set")` for the unset case.

## Data

Created by `Database` on its first successful connection, inside one transaction guarded by
`SELECT pg_advisory_xact_lock(7302002)` (constant key, so concurrent replicas/processes cannot race):

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq        bigserial   PRIMARY KEY,
    id         text        NOT NULL UNIQUE,
    title      text        NOT NULL,
    due_date   date        NULL,
    created_at timestamptz NOT NULL
);
```

- `add`: `id = str(uuid4())`, `created_at = datetime.now(UTC)` in Python; `INSERT ... RETURNING id, title, due_date,
  created_at`; the `Task` is built from the returned row.
- `list`: `SELECT id, title, due_date, created_at FROM tasks ORDER BY seq`.
- The "schema ready" flag is per `Database` instance, guarded by a `threading.Lock`; it is set only after the DDL
  committed, so a failed first attempt is retried on the next call (AC-002.7).
- In-memory tasks are not migrated (spec A2).

## Configuration

| Variable | Default | Use |
|---|---|---|
| `DATABASE_URL` | unset | libpq URI of the task database (injected by `uses: postgres`). Unset/empty: service starts, `/ready` and task routes answer 503. |

`PG*` variables are also injected; the service reads only `DATABASE_URL` (libpq still honours `PGPASSWORD` etc. as
fallbacks for parts missing from the URL). Documented in `docs/env-vars.md`.

## Test harness (contract for the testers)

`tests/pg_harness.py` holds the fixtures; `tests/conftest.py` imports them (`from pg_harness import clean_db,
pg_factory, pg_url, unreachable_url  # noqa: F401`; pytest puts `tests/` on `sys.path`, there is no `tests/__init__.py`),
so every test module can use them by name. Testers do not edit either file; their own helpers live in their test
modules. It needs `initdb`, `pg_ctl`, `pg_isready`, `psql` on `PATH` (devbox `postgresql@16`); when they are missing
and `TEST_DATABASE_URL` is unset, a test that uses a database fixture **fails** with "Postgres binaries not found: run
inside `devbox shell` / `devbox run test`" (never skips). Nothing starts unless a test asks for a fixture, so
`devbox run smoke` never starts Postgres.

| Fixture | Scope | Gives |
|---|---|---|
| `pg_url` | session | URL of a running throwaway Postgres (`postgresql://postgres@127.0.0.1:<port>/postgres`), or `TEST_DATABASE_URL`. Also sets `os.environ["DATABASE_URL"]` to it for the session (restored at the end). |
| `clean_db` | function | depends on `pg_url`; before the test runs `TRUNCATE TABLE tasks RESTART IDENTITY` when the table exists (via `psql`). Never drops the table. |
| `unreachable_url` | function | `postgresql://postgres@127.0.0.1:<port>/postgres` where `<port>` was just bound and released (a closed port). |
| `pg_factory` | function | `pg_factory.free_port() -> int` (a port bound and released); `pg_factory.start(port: int \| None = None) -> PgServer` starts another throwaway server (empty, no `tasks` table) on the given or a free port and returns once `pg_isready` answers; every server it started is stopped and deleted at teardown. |
| `client` | function | (changed) `TestClient(app)` for the module app, after `pg_url` and `clean_db`. |

`PgServer`: `.url: str`, `.port: int`, `.stop() -> None` (fast shutdown, data kept), `.start() -> None` (same data
directory and port).

How the criteria map onto it:

- "restart" (AC-002.1) = `create_app(pg_url)` again (or `server.stop()`/`start()` with a `pg_factory` server).
- "second process" (AC-002.2) = a second `create_app(pg_url)`, or a `uvicorn taskboard6_api.main:app` subprocess with
  `DATABASE_URL` set.
- "unreachable" (AC-002.4 to AC-002.6) = `create_app(unreachable_url)`, or `server.stop()`; "reachable again" in
  AC-002.4 = check the same database through a reachable app.
- AC-002.7 = `port = pg_factory.free_port()`, `create_app(f"postgresql://postgres@127.0.0.1:{port}/postgres")`,
  assert 503s, then `pg_factory.start(port)` and assert `200`s with the same app instance (the table is created on
  first use).
- Spec 001's acceptance tests (`tests/test_tasks.py`) keep their in-memory override and stay green; AC-002.3 tests run
  the same cases against `create_app(pg_url)` with `clean_db`.

CI: the template's `test` job runs `devbox run test`; `devbox-install-action` installs `postgresql@16` from
`devbox.json`, so the harness works there unchanged. No workflow change, no service container.

## Risks

- `initdb` refuses to run as root: a self-hosted runner that runs jobs as root must set `TEST_DATABASE_URL` (or run as
  a normal user). Tests that need `pg_factory` cannot use `TEST_DATABASE_URL` and would fail there; acceptable, the
  platform runners run as a normal user.
- A silent network partition (no RST) during a statement is bounded by `statement_timeout` only on the server side;
  `Database` also sets TCP keepalives (`keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=2`)
  to bound it on the client. Acceptable for one in-cluster database.
- Connect per request adds a handshake per call; fine for this load (ADR-001 names when to add a pool).
