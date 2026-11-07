"""Acceptance tests for spec 002 (store tasks in Postgres, answer 503)."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
UNAVAILABLE = {"detail": "Task storage is unavailable"}


def _app(url: str) -> Any:
    from taskboard6_api.main import create_app

    return create_app(url)


def _assert_422_for(response: Any, field: str) -> None:
    assert response.status_code == 422
    assert any(e["loc"][-1] == field for e in response.json()["detail"])


def test_tasks_survive_restart(pg_url: str, clean_db: None) -> None:  # AC-002.1
    with TestClient(_app(pg_url)) as first:
        created = [
            first.post("/tasks", json={"title": t, "due_date": d}).json()
            for t, d in [("A", None), ("B", "2026-01-01"), ("C", None)]
        ]
    with TestClient(_app(pg_url)) as second:
        response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created
    assert [t["title"] for t in created] == ["A", "B", "C"]
    assert all(CREATED_AT_RE.match(t["created_at"]) for t in created)


def test_tasks_survive_server_restart(pg_factory: Any) -> None:  # AC-002.1
    server = pg_factory.start()
    with TestClient(_app(server.url)) as c:
        created = [c.post("/tasks", json={"title": t}).json() for t in ("A", "B", "C")]
    server.stop()
    server.start()
    with TestClient(_app(server.url)) as c:
        response = c.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_second_process_sees_same_tasks(pg_url: str, clean_db: None) -> None:  # AC-002.2
    with TestClient(_app(pg_url)) as one, TestClient(_app(pg_url)) as two:
        created = [one.post("/tasks", json={"title": t}).json() for t in ("A", "B", "C")]
        assert two.get("/tasks").json() == created
        extra = two.post("/tasks", json={"title": "D"}).json()
        assert one.get("/tasks").json() == [*created, extra]


@pytest.fixture()
def pg_client(pg_url: str, clean_db: None) -> TestClient:
    return TestClient(_app(pg_url))


def test_pg_create_minimal_task(pg_client: TestClient) -> None:  # AC-002.3
    response = pg_client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date", "created_at"}
    assert str(uuid.UUID(body["id"])) == body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None
    assert CREATED_AT_RE.match(body["created_at"])


def test_pg_due_date_and_trim(pg_client: TestClient) -> None:  # AC-002.3
    response = pg_client.post("/tasks", json={"title": "  File taxes  ", "due_date": "2026-12-31"})
    assert response.status_code == 201
    assert response.json()["title"] == "File taxes"
    assert response.json()["due_date"] == "2026-12-31"
    assert pg_client.get("/tasks").json() == [response.json()]


def test_pg_title_200_after_trim_accepted(pg_client: TestClient) -> None:  # AC-002.3
    response = pg_client.post("/tasks", json={"title": " " + "x" * 200 + " "})
    assert response.status_code == 201
    assert response.json()["title"] == "x" * 200


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": 123}, {"title": None}, {"title": ""}, {"title": "   "}, {"title": "x" * 201}],
)
def test_pg_invalid_title_rejected(pg_client: TestClient, payload: dict) -> None:  # AC-002.3
    _assert_422_for(pg_client.post("/tasks", json=payload), "title")
    assert pg_client.get("/tasks").json() == []


@pytest.mark.parametrize("due", ["2026-02-30", "31.12.2026", "2026-12-31T10:00:00", "", 20261231])
def test_pg_invalid_due_date_rejected(pg_client: TestClient, due: object) -> None:  # AC-002.3
    _assert_422_for(pg_client.post("/tasks", json={"title": "Task", "due_date": due}), "due_date")
    assert pg_client.get("/tasks").json() == []


def test_pg_list_empty(pg_client: TestClient) -> None:  # AC-002.3
    response = pg_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_post_503_when_db_down_and_nothing_stored(pg_factory: Any) -> None:  # AC-002.4
    server = pg_factory.start()
    app = _app(server.url)
    with TestClient(app) as c:
        assert c.get("/tasks").status_code == 200
        server.stop()
        started = time.monotonic()
        response = c.post("/tasks", json={"title": "lost"})
        assert time.monotonic() - started < 5
        assert response.status_code == 503
        assert response.json() == UNAVAILABLE
        server.start()
        listed = c.get("/tasks")
    assert listed.status_code == 200
    assert all(t["title"] != "lost" for t in listed.json())


def test_post_503_unreachable_url(unreachable_url: str) -> None:  # AC-002.4
    with TestClient(_app(unreachable_url)) as c:
        started = time.monotonic()
        response = c.post("/tasks", json={"title": "x"})
    assert time.monotonic() - started < 5
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_get_503_when_db_down(unreachable_url: str) -> None:  # AC-002.5
    with TestClient(_app(unreachable_url)) as c:
        started = time.monotonic()
        response = c.get("/tasks")
    assert time.monotonic() - started < 5
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_ready_503_health_200_when_db_down(unreachable_url: str) -> None:  # AC-002.6
    with TestClient(_app(unreachable_url)) as c:
        ready = c.get("/ready")
        health = c.get("/health")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not ready"}
    assert health.status_code == 200


def test_recovers_without_restart(pg_factory: Any) -> None:  # AC-002.7
    port = pg_factory.free_port()
    with TestClient(_app(f"postgresql://postgres@127.0.0.1:{port}/postgres")) as c:
        assert c.get("/ready").status_code == 503
        assert c.get("/tasks").status_code == 503
        pg_factory.start(port)
        ready = c.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
        created = c.post("/tasks", json={"title": "back"})
        assert created.status_code == 201
        listed = c.get("/tasks")
    assert listed.status_code == 200
    assert listed.json() == [created.json()]
