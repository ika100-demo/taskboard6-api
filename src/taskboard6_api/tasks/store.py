"""Thread-safe in-memory task store."""

import threading
import uuid
from datetime import UTC, date, datetime
from typing import Protocol

from fastapi import Request

from taskboard6_api.tasks.models import Task


class TaskStorage(Protocol):
    """What the routes need from a task store."""

    def add(self, title: str, due_date: date | None) -> Task: ...

    def list(self) -> "list[Task]": ...


class TaskStore:
    """Keeps tasks in insertion order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: list[Task] = []

    def add(self, title: str, due_date: date | None) -> Task:
        task = Task(
            id=str(uuid.uuid4()),
            title=title,
            due_date=due_date,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._tasks.append(task)
        return task

    def list(self) -> "list[Task]":
        with self._lock:
            return list(self._tasks)

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()


def get_task_store(request: Request) -> TaskStorage:
    store: TaskStorage = request.app.state.task_store
    return store
