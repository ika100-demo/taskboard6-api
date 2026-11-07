# Design — 001 Create and list tasks

## Decisions

- **One `tasks` package** (`src/taskboard6_api/tasks/`) with a model, a store and an `APIRouter`, mounted in `main.py` with `app.include_router`. It keeps `main.py` to wiring and gives later specs (update, delete, durable storage) one place to grow.
- **In-memory store behind a FastAPI dependency.** `TaskStore` is a plain class holding a list guarded by a `threading.Lock` (sync endpoints run in the threadpool, so concurrent `POST`s must not interleave appends). One instance per process lives at module level; routes receive it via `Depends(get_task_store)`. Tests get a fresh store with `app.dependency_overrides[get_task_store] = lambda: store` (AC-001.6, AC-001.7 need a known-empty start). Durable storage is a non-goal; swapping the store later only changes `get_task_store`. Feature-local, so no ADR.
- **Validation with Pydantic v2 in the request model**, so errors use FastAPI's standard 422 shape (A4). `title` is a strict string (no coercion of numbers) stripped then length-checked (A3, AC-001.3, AC-001.5). `due_date` is validated as a strict string matching `^\d{4}-\d{2}-\d{2}$` and then `datetime.date.fromisoformat` — not Pydantic's `date` type, which in lax mode accepts Unix timestamps and `...T00:00:00` datetimes, contradicting AC-001.4.
- **Unknown fields are ignored** (`extra="ignore"`, Pydantic's default); client-sent `id` / `created_at` therefore never reach the store (A5).
- `id` is `str(uuid.uuid4())`; `created_at` is `datetime.now(timezone.utc)` taken by the store at insert.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `taskboard6_api/tasks/__init__.py` | package marker, re-exports `router` | new |
| `taskboard6_api/tasks/models.py` | `TaskCreate` (request), `Task` (response/stored) | new |
| `taskboard6_api/tasks/store.py` | `TaskStore` (`add`, `list`, `clear`), `get_task_store` dependency | new |
| `taskboard6_api/tasks/api.py` | `router = APIRouter()` with `POST /tasks`, `GET /tasks` | new |
| `taskboard6_api/main.py` | `app.include_router(tasks.router)` | changed |

Public Python interface (tests may rely on it):

```python
# tasks/store.py
class TaskStore:
    def add(self, title: str, due_date: datetime.date | None) -> Task: ...
    def list(self) -> list[Task]: ...      # copy, in insertion order
    def clear(self) -> None: ...
def get_task_store() -> TaskStore: ...     # returns the process-wide instance
```

## Contract

No authentication on either endpoint. JSON in and out (`Content-Type: application/json`).

### Task object

| Field | Type | Notes |
|---|---|---|
| `id` | string | server-assigned UUID4 in canonical form; unique (AC-001.1, AC-001.7) |
| `title` | string | 1..200 characters, surrounding whitespace removed (AC-001.5) |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, past dates allowed (A2) |
| `created_at` | string | ISO 8601 UTC with `Z` suffix and microseconds, e.g. `"2026-11-07T09:15:02.123456Z"` (AC-001.1) |

Exactly these four keys, always present.

### `POST /tasks`

Request body: `{"title": string, "due_date"?: string | null}`. Any other key is ignored. `due_date` absent or `null` both mean no due date.

- `201 Created`, body: the created Task object (AC-001.1, AC-001.2). No `Location` header (single-task fetch is a non-goal).
- `422 Unprocessable Entity`, body: FastAPI's standard validation error, nothing stored:

```json
{"detail": [{"type": "<pydantic error type>", "loc": ["body", "<field>"], "msg": "<text>", "input": <value>}]}
```

| Case | `loc` | AC |
|---|---|---|
| `title` missing | `["body","title"]` (`type: "missing"`) | AC-001.3 |
| `title` not a string (number, bool, null, object, array) | `["body","title"]` | AC-001.3 |
| `title` empty / whitespace only / > 200 chars after trimming | `["body","title"]` | AC-001.3 |
| `due_date` not a string, not `YYYY-MM-DD`, or not a real calendar date (`"2026-02-30"`, `"31.12.2026"`, `"2026-12-31T10:00:00"`) | `["body","due_date"]` | AC-001.4 |
| body not a JSON object / malformed JSON | `["body"]` or `["body", <pos>]` (FastAPI default) | — |

Tests assert the status code and that some entry in `detail` has `loc[-1] == "title"` (or `"due_date"`); `msg` and `type` texts are not part of the contract. When both fields are invalid both entries appear.

### `GET /tasks`

- `200 OK`, body: JSON array of Task objects in creation order (oldest first), unbounded (A6, AC-001.6, AC-001.7). `[]` when none exist. Each element is identical to the body `POST /tasks` returned for it.

## Data

In memory only: `list[Task]` in the `TaskStore` instance. Lost on restart, not shared between replicas (non-goal).

## Testing notes

- In-process tests: override `get_task_store` with a fresh `TaskStore()` per test (or call `get_task_store().clear()`), because the conftest `client` fixture shares the module-level `app`.
- Smoke tests against a deployed instance cannot assume an empty store: the read-only smoke for AC-001.6 checks `200` and a JSON array; the writing smoke for AC-001.1 (`@pytest.mark.writes`) creates `smoke-<uuid>` titles.

## Risks

- Unbounded memory growth: accepted for this spec (no durable storage, list without limit per A6); a later storage spec replaces the store.
- Multiple replicas would each hold different tasks; the gitops entry should keep one replica until storage exists (no change needed if it already runs one).
