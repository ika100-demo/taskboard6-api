"""PostgreSQL-backed task store."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from taskboard6_api.db import Database
from taskboard6_api.tasks.models import Task


class PostgresTaskStore:
    """Durable task store; raises StorageUnavailableError when the DB is unusable."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, title: str, due_date: date | None) -> Task:
        with self._db.connection() as conn:
            row = conn.execute(
                "INSERT INTO tasks (id, title, due_date, created_at) VALUES (%s, %s, %s, %s)"
                " RETURNING id, title, due_date, created_at",
                (str(uuid4()), title, due_date, datetime.now(UTC)),
            ).fetchone()
        assert row is not None  # nosec B101
        return Task(id=row[0], title=row[1], due_date=row[2], created_at=row[3])

    def list(self) -> list[Task]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT id, title, due_date, created_at FROM tasks ORDER BY seq"
            ).fetchall()
        return [Task(id=r[0], title=r[1], due_date=r[2], created_at=r[3]) for r in rows]
