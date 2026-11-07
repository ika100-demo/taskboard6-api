# Verification — 001 Create and list tasks

**Result:** pass
**Commit:** 387d0ff · **Base:** 8805138 · **Trace:** 7/7 criteria named by tests (smoke: AC-001.1, AC-001.6)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_minimal_task`, `tests/test_smoke_tasks.py::test_ac_001_1_create_task_returns_201` | `src/taskboard6_api/tasks/api.py:17`, `src/taskboard6_api/tasks/store.py:17-26`, `src/taskboard6_api/tasks/models.py:54-57` | Asserts 201, exactly four keys, canonical UUID string id, title, `due_date` null, `created_at` matching `...\.\d{6}Z`. Smoke test is marked `writes` and uses `smoke-<uuid>` titles. |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_with_due_date` | `src/taskboard6_api/tasks/models.py:29-39`, `:50-52` | Asserts 201 and `due_date == "2026-12-31"`. |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_rejected` (10 cases), `::test_title_of_200_chars_after_trim_accepted` | `src/taskboard6_api/tasks/models.py:17-20`, `:26` | Covers missing, number, bool, null, object, array, empty, whitespace, 201 chars, 201 chars with padding. Each case asserts 422 with `loc[-1] == "title"`, and `GET /tasks == []` shows nothing was stored. The 200-char boundary is accepted. `StrictStr` blocks type coercion. |
| AC-001.4 | met | `tests/test_tasks.py::test_invalid_due_date_rejected` (7 cases) | `src/taskboard6_api/tasks/models.py:15`, `:29-39` | Covers the three examples from the spec plus `""`, `"tomorrow"`, an integer timestamp and `true`. Each case asserts 422 with `loc[-1] == "due_date"`, and nothing is stored. |
| AC-001.5 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/taskboard6_api/tasks/models.py:19` (`strip_whitespace=True`) | Asserts the trimmed title in both the POST response and the GET list. |
| AC-001.6 | met | `tests/test_tasks.py::test_list_empty`, `tests/test_smoke_tasks.py::test_ac_001_6_list_tasks_returns_json_array` | `src/taskboard6_api/tasks/api.py:25-28`, `src/taskboard6_api/tasks/store.py:37` | Asserts 200 and `[]` on a fresh store. The process-wide store also starts empty (`store.py:37`). Smoke is read-only (200 plus a JSON array), as the design's testing notes say, because a shared environment is not empty. |
| AC-001.7 | met | `tests/test_tasks.py::test_list_in_creation_order` | `src/taskboard6_api/tasks/store.py:24-30` | Asserts that the GET body equals the list of POST bodies (same id, title, due_date and created_at, order A, B, C, exactly three) and that the ids are distinct. |

## Non-goals

None of the excluded features were added: no update, complete or delete, no single-task fetch (no `Location` header), no filter, sort or pagination, no durable storage, no auth, no extra fields. `Task` has exactly four fields (`models.py:42-48`). `main.py` only gains the import and `app.include_router(tasks.router)` (`main.py:12`, `:23`). The health, ready, ping and metrics endpoints and the middleware are untouched. ✔

## Deviations from the plan

- **t1 `TaskCreate.due_date` typed `date | None` with a `mode="before"` validator, where the plan said `str | None` with an after-validator** (`models.py:27-39`). Acceptable. The before-validator runs first and rejects anything that is not a string matching `^\d{4}-\d{2}-\d{2}$` (checked with `fullmatch`), or that `date.fromisoformat` cannot parse. Pydantic's lax `date` parsing therefore never sees raw input, so timestamps, datetimes and booleans are rejected (the tests cover all three). The error is still reported at `loc ["body","due_date"]`. The only visible side effect is that the OpenAPI schema advertises `format: date` for `due_date`, which matches the contract.
- **Files outside every task's `files`:** `tests/test_tasks.py` and `tests/test_smoke_tasks.py` (acceptance tests from the red commit 82c6c57), `tests/test_tasks_store.py` (unit tests the t1 notes ask for), and the spec, plan and design docs (status, changelog, plan bookkeeping). All acceptable.
- All tasks (t1, t2) are `done: true`. t2 notes are followed: sync handlers, `status_code=201`, `response_model`, `Depends(get_task_store)`, no custom exception handler, and a `task_created` log line with `task_id` only, never the title (`api.py:21`).

## Contract

Matches `design.md`:
- Status codes 201, 200 and 422, with FastAPI's default 422 shape.
- Exactly four keys in each task.
- `id` is `str(uuid.uuid4())`.
- `created_at` is UTC with microseconds and a `Z` suffix (`models.py:54-57`).
- `due_date` is `YYYY-MM-DD` or null.
- Unknown keys are ignored (Pydantic's default `extra`).
- The list is returned in insertion order, as a copy, behind a lock (`store.py:24-34`).
- The public interface `TaskStore.add/list/clear` and `get_task_store` matches the design. ✔

## Mutation check (report only)

16 of 17 mutants of the changed code were caught by the acceptance tests (94 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard6_api/tasks/store.py:41 return value → None`
