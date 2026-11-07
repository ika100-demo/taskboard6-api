"""Acceptance tests for spec 001 (create and list tasks)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard6_api.main import app

CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


@pytest.fixture()
def tasks_client() -> Iterator[TestClient]:
    from taskboard6_api.tasks.store import TaskStore, get_task_store

    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def _assert_422_for(response: Any, field: str) -> None:
    assert response.status_code == 422
    assert any(e["loc"][-1] == field for e in response.json()["detail"])


def test_create_minimal_task(tasks_client: TestClient) -> None:  # AC-001.1
    response = tasks_client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date", "created_at"}
    assert isinstance(body["id"], str)
    assert str(uuid.UUID(body["id"])) == body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None
    assert CREATED_AT_RE.match(body["created_at"])


def test_create_task_with_due_date(tasks_client: TestClient) -> None:  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-31"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-12-31"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": 123},
        {"title": True},
        {"title": None},
        {"title": {"a": 1}},
        {"title": ["x"]},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "  " + "x" * 201 + "  "},
    ],
)
def test_invalid_title_rejected(tasks_client: TestClient, payload: dict) -> None:  # AC-001.3
    _assert_422_for(tasks_client.post("/tasks", json=payload), "title")
    assert tasks_client.get("/tasks").json() == []


def test_title_of_200_chars_after_trim_accepted(tasks_client: TestClient) -> None:  # AC-001.3
    response = tasks_client.post("/tasks", json={"title": " " + "x" * 200 + " "})
    assert response.status_code == 201
    assert response.json()["title"] == "x" * 200


@pytest.mark.parametrize(
    "due", ["2026-02-30", "31.12.2026", "2026-12-31T10:00:00", "", "tomorrow", 20261231, True]
)
def test_invalid_due_date_rejected(tasks_client: TestClient, due: object) -> None:  # AC-001.4
    response = tasks_client.post("/tasks", json={"title": "Task", "due_date": due})
    _assert_422_for(response, "due_date")
    assert tasks_client.get("/tasks").json() == []


def test_title_is_trimmed(tasks_client: TestClient) -> None:  # AC-001.5
    response = tasks_client.post("/tasks", json={"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"
    assert [t["title"] for t in tasks_client.get("/tasks").json()] == ["Buy milk"]


def test_list_empty(tasks_client: TestClient) -> None:  # AC-001.6
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_list_in_creation_order(tasks_client: TestClient) -> None:  # AC-001.7
    created = [
        tasks_client.post("/tasks", json={"title": t, "due_date": d}).json()
        for t, d in [("A", None), ("B", "2026-01-01"), ("C", None)]
    ]
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created
    assert [t["title"] for t in created] == ["A", "B", "C"]
    assert len({t["id"] for t in created}) == 3
