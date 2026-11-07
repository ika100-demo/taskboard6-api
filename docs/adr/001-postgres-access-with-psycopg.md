# ADR-001: Postgres access with psycopg 3, one connection per request, schema created in code

## Status

Accepted (spec 002, 2026-11-07).

## Context

Spec 002 moves tasks from memory into the system's CloudNativePG Postgres (injected as `DATABASE_URL` by the
gitops-app's `uses: postgres`). The service must start and keep `/health` green while the database is down, answer
`503` within 5 s while it is unreachable, and recover without a restart once it is back. There is one table and no
migration tool in this repo. Handlers are synchronous FastAPI endpoints (threadpool).

## Decision

- **Driver:** `psycopg[binary]` 3 (sync API). The binary wheel bundles libpq, so the slim runtime image needs no system
  package.
- **Connections:** one short-lived connection per store call (`psycopg.connect(url, connect_timeout=2,
  options="-c statement_timeout=2000")`), closed at the end of the call. No `psycopg_pool` for now: a pool's background
  reconnect with exponential backoff (up to `reconnect_timeout`) makes "reachable again" non-deterministic, and a
  stale pooled connection is the exact failure the spec asks us to survive. A connection per call has no stale state;
  the next request after an outage simply connects. Revisit (add `psycopg_pool` with `check=check_connection`) when
  request rate makes connect latency matter.
- **Schema:** the `Database` object runs an idempotent `CREATE TABLE IF NOT EXISTS` (under a transaction-scoped
  advisory lock, so concurrent replicas cannot race on the catalog) on its first successful connection. A migration
  tool (Alembic) is introduced by the first spec that changes an existing column.
- **Errors:** every `psycopg.OperationalError` (connection refused, timeout, statement timeout, server shutdown) and a
  missing `DATABASE_URL` become one domain error, `StorageUnavailableError`, that the app maps to `503`.

## Consequences

**Positive:** stateless processes, deterministic recovery, no background threads, simple tests ("unreachable" is a
closed port, "restart" is a new app instance on the same database).

**Negative:** one TCP + auth handshake per request (a few ms in-cluster); a later schema change needs a real migration
tool and a decision on how it runs (init container or startup job).
