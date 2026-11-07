---
spec_id: 002-store-tasks-in-postgres-and-answer-503
title: Store tasks in Postgres and answer 503 and not-ready while the database is unreachable
status: done
priority: P1
shape: service-python
parent: ika100-demo/taskboard6-gitops:001-persistent-tasks-and-task-ui
---

# 002 — Store tasks in Postgres and answer 503 and not-ready while the database is unreachable

## Problem

The taskboard6 system can create and list tasks only through its API, and the API keeps them in memory: every restart or redeploy loses every task, so nobody can rely on the board. Using it also requires sending HTTP requests by hand, because the web app is still the starter page. Now that both components run in dev, tasks should survive restarts and people should be able to see and add them in the browser.

## System context

Slice of the system plan `001-persistent-tasks-and-task-ui` in `ika100-demo/taskboard6-gitops` for `taskboard6-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks A, B and C were created through `POST /tasks` in that order, when the API is restarted or redeployed and a client then sends `GET /tasks`, then the response is `200` with exactly those three tasks in creation order, each with the same `id`, `title`, `due_date` and `created_at` returned when it was created.
- **AC-001.2** Given the API cannot reach its database, when a client sends `POST /tasks` with a valid body or `GET /tasks`, then the response is `503` with a JSON error body, no task is created, and the API's readiness endpoint answers with a non-`200` status until the database is reachable again.

### Contract

The API contract is taskboard6-api spec 001, unchanged, plus the `503` answers of this spec. The web app reads
`TASKBOARD6_API_URL` (no trailing slash; dev: `http://taskboard6-api`) and calls the API only from its server.

**Task (JSON):** `{"id": string (UUID), "title": string (trimmed, 1 to 200 chars), "due_date": "YYYY-MM-DD" | null,
"created_at": "YYYY-MM-DDTHH:MM:SS.ffffffZ" (UTC)}`.

**API `GET /tasks`** (no auth, no query parameters)
- `200`: JSON array of Task, oldest first (creation order), no limit; `[]` when none.
- `503`: `{"detail": "Task storage is unavailable"}` when the database is unreachable.

**API `POST /tasks`** (no auth) body `{"title": string, "due_date": "YYYY-MM-DD" | null}`; `due_date` may be omitted
(= `null`); unknown fields, `id` and `created_at` are ignored.
- `201`: the created Task.
- `422`: FastAPI standard shape `{"detail": [{"loc": ["body", "<field>"], "msg": string, "type": string}, ...]}`; the
  field is `title` or `due_date`. No task is created.
- `503`: `{"detail": "Task storage is unavailable"}`; no task is created.

**API `GET /ready`**: `200` `{"status": "ready"}` when the database answers; `503` `{"status": "not ready"}` otherwise.
**API `GET /health`**: `200` always while the process runs (does not check the database).

**Web `GET /`**: server-rendered on every request (no static caching). Always answers `200`. Shows the create form
(fields labelled "Title" and "Due date" (`<input type="date">`), button "Add task") above either the task list (one
item per task, title and `due_date` or "No due date"), "No tasks yet", or "Tasks could not be loaded. Please try again
later.". The form is shown in all three states.

**Web `POST /api/tasks`** (the web app's own route handler, called by the form): body `{"title": string, "due_date":
"YYYY-MM-DD" | null}`, forwarded unchanged to the API's `POST /tasks`.
- API `201` -> `201` with the Task; the page appends it to the end of the list (removing "No tasks yet") and clears
  both fields.
- API `422` -> `422` with the API's body unchanged; the page shows the first `msg` whose `loc` ends in `title` next to
  the title field (and one whose `loc` ends in `due_date` next to the due date field); values stay.
- anything else (API `5xx`, unlisted status, unreachable, timeout) -> `502` `{"detail": "upstream unavailable"}`; the
  page shows "The task could not be saved. Please try again." near the button; values stay.

**Client-side title check** (before any request): trim; empty -> "Please enter a title."; more than 200 characters ->
"The title must be at most 200 characters."; shown next to the title field, nothing is sent. A failed or successful
new submit replaces the previous message.

### Errors

- API errors are JSON with a top-level `detail`: a string for `503`, the FastAPI list for `422`. The API never answers
  an HTML error page; an unexpected failure is `500` `{"detail": "Internal Server Error"}`.
- Web route handler errors are JSON `{"detail": ...}` as above.
- A caller treats any status the contract does not list for that call, a body that is not the documented JSON, a
  connection error or a timeout exactly like a `5xx`: the web page shows "Tasks could not be loaded. Please try again
  later." (list) or "The task could not be saved. Please try again." (create). The web app never retries a `POST`
  (to avoid duplicates); the user retries.
- The API logs every `503` with the database error (structlog, no credentials in the log).

### Timeouts

- Web server -> API `GET /tasks`: 3 s total; on timeout, the list error message (page still `200`).
- Web server -> API `POST /tasks`: 3 s total; on timeout, `502` to the browser and the save error message.
- Browser -> web `POST /api/tasks`: 4 s client-side abort; on abort, the save error message. Together this keeps
  AC-001.5's 5-second budget.
- API -> Postgres: connect timeout 2 s, statement timeout 2 s; on either, the task routes answer `503` (well inside 5 s)
  and `/ready` answers `503`. A pooled connection that has gone bad is discarded and the next request reconnects; no
  restart is needed once the database is back.
- API `/ready` -> Postgres: `SELECT 1` with a 1 s timeout (the probe's own timeout is the platform default).

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Config: `DATABASE_URL` (injected by the gitops-app's `uses: postgres`, also `PG*`); the service must start and
keep `/health` green when it is unset or the database is down (then `/ready` and the task routes answer 503).
Suggested: psycopg 3 with psycopg_pool, an idempotent `CREATE TABLE IF NOT EXISTS` on the first successful
connection (no migration tool needed for one table). Table `tasks`: `seq bigserial primary key`, `id text unique`
(UUID string), `title text not null`, `due_date date null`, `created_at timestamptz not null`; list
`ORDER BY seq` so ties in `created_at` keep creation order. Keep the TaskStore seam so the route code stays.
Tests need a real Postgres (devbox service or testcontainers); "restart" = a new app instance on the same DB;
"unreachable" = a DATABASE_URL pointing at a closed port. In-memory tasks are not migrated (spec A2).

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given tasks A, B and C were created through `POST /tasks` in that order, when the service is stopped and started again with the same `DATABASE_URL` and a client sends `GET /tasks`, then the response is `200` with exactly A, B, C in that order, each with the same `id`, `title`, `due_date` and `created_at` (to the microsecond) returned by its `POST /tasks` (system AC-001.1)
- **AC-002.2** Given tasks were created in one service process, when a second service process using the same `DATABASE_URL` answers `GET /tasks`, then it returns the same tasks in the same creation order (system AC-001.1)
- **AC-002.3** Given a running service with a reachable database, when a client uses `POST /tasks` and `GET /tasks`, then paths, fields, trimming, the 1 to 200 character title rule, the `YYYY-MM-DD` due date rule and the `422` error shape behave exactly as in taskboard6-api spec 001 (system AC-001.1)
- **AC-002.4** Given the database is unreachable, when a client sends `POST /tasks` with a valid body, then the response is `503` with JSON body `{"detail": "Task storage is unavailable"}` within 5 seconds, and once the database is reachable again `GET /tasks` does not contain that task (system AC-001.2)
- **AC-002.5** Given the database is unreachable, when a client sends `GET /tasks`, then the response is `503` with JSON body `{"detail": "Task storage is unavailable"}` within 5 seconds (system AC-001.2)
- **AC-002.6** Given the database is unreachable, when the readiness endpoint `GET /ready` is called, then it answers `503` with JSON `{"status": "not ready"}`, while `GET /health` still answers `200` (system AC-001.2)
- **AC-002.7** Given the service started while the database was unreachable, when the database becomes reachable, then without a restart `GET /ready` answers `200` and `POST /tasks` and `GET /tasks` work again, the schema being created on first use (system AC-001.2)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- 2026-11-07 created from the system plan, with its criteria (spec 147)
- 2026-11-07 approved
- 2026-11-07 building
- 2026-11-07 done
