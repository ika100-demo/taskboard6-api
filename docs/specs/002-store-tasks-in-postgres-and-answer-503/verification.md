# Verification — 002 Store tasks in Postgres and answer 503 and not-ready while the database is unreachable

**Result:** pass
**Commit:** 0e5ef92 · **Base:** 5afaa12 · **Trace:** 7/7 criteria named by tests (`tests/test_tasks_postgres.py`), none missing

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_tasks_survive_restart`, `::test_tasks_survive_server_restart` | `src/taskboard6_api/tasks/pg_store.py:18-33`, `src/taskboard6_api/db.py:17-25`, `src/taskboard6_api/main.py:36-37` | A, B, C created through one app, `GET /tasks` from a new `create_app(pg_url)` (and after a real `pg_ctl` stop/start) equals the POST bodies exactly (id, title, due_date, created_at string with 6 fractional digits); order by `seq`. |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_second_process_sees_same_tasks` | `src/taskboard6_api/tasks/pg_store.py:28-33`, `src/taskboard6_api/main.py:36-37` | Two independent app instances (own `Database` each) on one URL see the same list in creation order, in both directions. |
| AC-002.3 | met | `tests/test_tasks_postgres.py::test_pg_create_minimal_task`, `::test_pg_due_date_and_trim`, `::test_pg_title_200_after_trim_accepted`, `::test_pg_invalid_title_rejected`, `::test_pg_invalid_due_date_rejected`, `::test_pg_list_empty` | `src/taskboard6_api/tasks/api.py:14-28` (routes unchanged), `src/taskboard6_api/tasks/models.py` (unchanged) | Runs spec 001's cases against `create_app(pg_url)`: four keys, UUID id, trimming, 1–200 rule, strict `YYYY-MM-DD`, 422 with `loc` ending in the field, nothing stored on 422, `[]` when empty. Full 422 shape is additionally covered by spec 001's `tests/test_tasks.py` (in-memory override, unchanged validation path). |
| AC-002.4 | met | `tests/test_tasks_postgres.py::test_post_503_when_db_down_and_nothing_stored`, `::test_post_503_unreachable_url` | `src/taskboard6_api/db.py:46-59` (connect_timeout=2, statement_timeout=2000, OperationalError -> StorageUnavailableError), `src/taskboard6_api/db.py:72-87` (rollback on error), `src/taskboard6_api/main.py:39-47` (503 handler) | Asserts 503, exact body, < 5 s, and after `server.start()` the same app's `GET /tasks` does not contain the task. |
| AC-002.5 | met | `tests/test_tasks_postgres.py::test_get_503_when_db_down` | `src/taskboard6_api/db.py:46-59`, `src/taskboard6_api/main.py:39-47` | 503, exact body, < 5 s. |
| AC-002.6 | met | `tests/test_tasks_postgres.py::test_ready_503_health_200_when_db_down` | `src/taskboard6_api/main.py:58-63` (`/ready` via `ping`), `src/taskboard6_api/db.py:89-99` (`ping`, statement_timeout=1000, never raises, logs at debug), `src/taskboard6_api/main.py:53-56` (`/health` unchanged) | `/ready` 503 `{"status": "not ready"}`, `/health` 200. |
| AC-002.7 | met | `tests/test_tasks_postgres.py::test_recovers_without_restart` | `src/taskboard6_api/db.py:61-70` (schema flag set only after commit, retried next call), `src/taskboard6_api/main.py:31-37` (no startup/import DB access) | App created against a free port: 503 on `/ready` and `/tasks`; then a server starts on that port and the same app instance answers `/ready` 200 `{"status":"ready"}`, POST 201 and GET returns that task (table created on first use). |

## System context

- Contract: 503 body `{"detail": "Task storage is unavailable"}` (`main.py:47`), `/ready` bodies (`main.py:62-63`), `/health` never touches the DB (`main.py:53-56`). ✔
- Errors: unexpected exceptions answer JSON `500 {"detail": "Internal Server Error"}` (`main.py:49-51`); `tests/test_metrics.py::test_unhandled_error_is_500_and_counted` still passes (status only, body not asserted; not an acceptance criterion). ✔
- Timeouts: connect 2 s / statement 2 s for task routes, 1 s statement for `/ready` (`db.py:46-57`, `db.py:74`, `db.py:91`), plus TCP keepalives per design Risks. No pool, so no stale pooled connection exists (design/ADR-001 decision; spec's "pooled connection discarded" requirement is satisfied trivially). ✔
- Logging: every task-route 503 logs `task_storage_unavailable` at warning with `error_type` and `error=str(exc)` (`main.py:41-46`); the message comes from psycopg / the fixed "DATABASE_URL is not set" string and never includes the URL (`db.py:43`, `db.py:59`, `db.py:82`). `tests/test_db.py::test_message_has_no_password` checks a `user:secret@` URL does not leak the password into the exception text. No test asserts the log event itself; code reviewed, acceptable since it is not an active criterion.
- Startup with `DATABASE_URL` unset: `Database._resolve_url` raises `StorageUnavailableError` lazily (`db.py:40-44`); `tests/test_db.py::test_unset_url_raises`, `::test_empty_url_raises`. ✔

## Non-goals

The spec lists no non-goals. Nothing beyond the spec was built: no web code, no migration of in-memory tasks (A2), no pool. No template-owned layout touched (API service; `/health`, `/ping`, `/metrics` moved into `create_app` with unchanged behaviour). ✔

## Deviations from the plan

- `devbox.lock` changed, in no task's `files`: generated by devbox from the `postgresql@16` package added in t1's `devbox.json`. Acceptable.
- `docs/adr/001-postgres-access-with-psycopg.md`, `spec.md`, `design.md`, `plan.md`: design/planning artefacts written before the build. Acceptable.
- Commit `dbed2e7` edited the acceptance tests after the red commit: moved `from taskboard6_api.main import create_app` from module level into a helper `_app()` so collection does not fail before `create_app` exists. No assertion, case or criterion id changed. Acceptable (not a weakening).
- Spec "Notes for this repo" suggested `psycopg_pool`; design and ADR-001 chose a connection per call instead, recorded with the reason (predictable recovery for AC-002.7). Acceptable.
- All four tasks are `done: true`.

## Contract

Matches `design.md`: public interface (`Database`, `StorageUnavailableError`, `PostgresTaskStore`, `TaskStorage`, `get_task_store(request)`, `create_app(database_url=None)`, module-level `app`), DDL and advisory lock key 7302002 (`db.py:15-25`, `db.py:67-69`), `ORDER BY seq` (`pg_store.py:31`), Python-side `uuid4`/`datetime.now(UTC)` (`pg_store.py:23`). ✔

## Mutation check (report only)

13 of 20 mutants of the changed code were caught by the acceptance tests (65 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard6_api/db.py:15 7302002 → 7302003`
- `src/taskboard6_api/db.py:70 True → False`
- `src/taskboard6_api/db.py:91 1000 → 1001`
- `src/taskboard6_api/db.py:51 2 → 3`
- `src/taskboard6_api/db.py:54 5 → 6`
- `src/taskboard6_api/db.py:56 2 → 3`
- `src/taskboard6_api/main.py:73 return value → None`
