---
spec_id: 001-create-and-list-tasks
shape: service-python
spec_hash: 4d3f4ba30c3b
summary: In-memory POST /tasks and GET /tasks with title and optional due date
tasks:
  - id: t1
    title: Add Task models and in-memory TaskStore
    files: [src/taskboard6_api/tasks/models.py, src/taskboard6_api/tasks/store.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.7]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add tasks router and mount it in the app
    files: [src/taskboard6_api/tasks/__init__.py, src/taskboard6_api/tasks/api.py, src/taskboard6_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: false
    depends_on: [t1]
---

# Plan — 001 Create and list tasks

Contract and module layout: [design.md](design.md).

## t1 — Add Task models and in-memory TaskStore

**Files:** src/taskboard6_api/tasks/models.py, src/taskboard6_api/tasks/store.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.7
**Goal:** the validated request model, the response model and a thread-safe in-memory store that assigns ids and timestamps and keeps insertion order.

**Implementation notes:**
- `TaskCreate`: `title` as strict `str` with whitespace stripping and length 1..200 applied after stripping (`Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]`); `due_date: str | None = None` with a `field_validator` that requires `^\d{4}-\d{2}-\d{2}$` and `date.fromisoformat`, converting to `datetime.date`. Do not use Pydantic's `date` type for input (it accepts timestamps and midnight datetimes). Extra keys ignored.
- `Task`: `id: str`, `title: str`, `due_date: date | None`, `created_at: datetime`; serialization must give `due_date` as `YYYY-MM-DD` and `created_at` as UTC with a `Z` suffix (add a `field_serializer` if the default emits `+00:00`).
- `TaskStore` with `add(title, due_date) -> Task` (uuid4 id, `datetime.now(timezone.utc)`), `list() -> list[Task]` (a copy, insertion order), `clear()`; a `threading.Lock` around mutation and read.
- Module-level instance plus `get_task_store() -> TaskStore` returning it.
- Unit tests for the store and models in `tests/test_tasks_store.py` (ordering, distinct ids, UTC timestamp, date edge cases).

**Done when:** the unit tests pass and `devbox run quality` is clean; the HTTP acceptance tests pass after t2.

## t2 — Add tasks router and mount it in the app

**Files:** src/taskboard6_api/tasks/__init__.py, src/taskboard6_api/tasks/api.py, src/taskboard6_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** expose `POST /tasks` (201) and `GET /tasks` (200) exactly as in the design contract.

**Implementation notes:**
- `api.py`: `router = APIRouter(tags=["tasks"])`; `POST /tasks` with `status_code=201`, `response_model=Task`, body `TaskCreate`, store via `Depends(get_task_store)`; `GET /tasks` with `response_model=list[Task]`.
- Sync (`def`) handlers, like the existing endpoints.
- `tasks/__init__.py` re-exports `router`; `main.py` adds `app.include_router(tasks.router)` after the middleware; leave health/ready/ping/metrics untouched.
- Validation errors stay FastAPI's default 422 handler; no custom exception handler.
- Log one structured event per created task (`task_created`, with `task_id`), never the title.

**Done when:** all acceptance tests for AC-001.1 to AC-001.7 pass, existing health/metrics tests still pass, and `devbox run ci` is green.
