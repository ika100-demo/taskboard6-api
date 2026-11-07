---
spec_id: 001-create-and-list-tasks
title: Create and list tasks
status: done
priority: P1
shape: service-python
---

# 001 — Create and list tasks

## Problem

The Task API so far answers only health, readiness and ping: a caller cannot record a single task. Clients that want to track work need a place to put a task with a title and, optionally, a date it is due, and to read back everything recorded so far. This is the first feature of the service; it keeps tasks in memory so that the API contract can be used and tested now, before any storage decision.

## Stories

As an API client, I want to create a task with a title and an optional due date, so that I can record work to be done.

As an API client, I want to list all tasks, so that I can see what has been recorded.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with JSON `{"title": "Buy milk"}`, then the response is `201` with a JSON task containing a server-assigned string `id`, `title` `"Buy milk"`, `due_date` `null` and `created_at` as an ISO 8601 UTC timestamp. (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-31"}`, then the response is `201` and the returned task has `due_date` `"2026-12-31"`.
- **AC-001.3** Given a running service, when a client sends `POST /tasks` with the title missing, not a string, empty or only whitespace, or longer than 200 characters after trimming, then the response is `422` with an error naming the `title` field, and no task is created.
- **AC-001.4** Given a running service, when a client sends `POST /tasks` with a `due_date` that is not a valid calendar date in `YYYY-MM-DD` form (for example `"2026-02-30"`, `"31.12.2026"` or `"2026-12-31T10:00:00"`), then the response is `422` with an error naming the `due_date` field, and no task is created.
- **AC-001.5** Given a title with leading or trailing whitespace such as `"  Buy milk  "`, when the task is created, then the returned and listed `title` is `"Buy milk"`.
- **AC-001.6** Given no task has been created since the service started, when a client sends `GET /tasks`, then the response is `200` with the JSON array `[]`. (smoke)
- **AC-001.7** Given tasks A, B and C were created in that order, when a client sends `GET /tasks`, then the response is `200` with a JSON array of exactly those three tasks in creation order (A, B, C), each with the same `id`, `title`, `due_date` and `created_at` returned when it was created, and all `id`s distinct.

## Non-goals

- Updating, completing or deleting tasks.
- Fetching a single task by id, filtering, sorting options or pagination of the list.
- Durable storage: tasks do not survive a restart and are not shared between replicas.
- Authentication, access control, users or per-user task lists: anyone who can reach the service may create and list tasks; access control comes in a later spec.
- Descriptions, priorities, tags or any field beyond title and due date.

## Assumptions

- **A1** The endpoints are `POST /tasks` and `GET /tasks`, with JSON bodies and fields `id`, `title`, `due_date`, `created_at` (other option: other paths or field names such as `dueDate`; affects AC-001.1, AC-001.2, AC-001.6, AC-001.7).
- **A2** The due date is a calendar date `YYYY-MM-DD` without time or time zone, and dates in the past are accepted (other option: date-time with time zone, or reject past dates; affects AC-001.2, AC-001.4).
- **A3** A title is 1 to 200 characters after trimming surrounding whitespace; duplicate titles are allowed (other option: no upper limit, or unique titles; affects AC-001.3, AC-001.5).
- **A4** Validation errors answer `422` in the framework's standard error shape, which names the offending field (other option: `400` with a custom error body; affects AC-001.3, AC-001.4).
- **A5** `id` is a server-generated opaque string (a UUID); any `id` or `created_at` sent by the client is ignored, as are unknown fields (other option: sequential integer ids, or rejecting unknown fields; affects AC-001.1, AC-001.7).
- **A6** The list returns all tasks in creation order without a limit, since tasks live only in memory until restart (other option: newest first, or a page size; affects AC-001.7).

## Open questions

- ~~May anyone who can reach the service create and list tasks, without authentication?~~ Answered 2026-11-07: yes, no authentication for now; access control comes in a later spec (see Non-goals; AC-001.1, AC-001.6, AC-001.7 need no credentials).

## Changelog

- 2026-11-07 created
- 2026-11-07 amended: open question on access answered (no authentication for now), folded into Non-goals
- 2026-11-07 approved
- 2026-11-07 building
- 2026-11-07 done
