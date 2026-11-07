"""Unit tests for task models and the in-memory store."""

from datetime import UTC, date

import pytest
from pydantic import ValidationError

from taskboard6_api.tasks.models import TaskCreate
from taskboard6_api.tasks.store import TaskStore, get_task_store


def test_store_order_and_distinct_ids() -> None:
    store = TaskStore()
    added = [store.add(t, None) for t in ("A", "B", "C")]
    assert store.list() == added
    assert len({t.id for t in added}) == 3


def test_list_returns_copy_and_clear() -> None:
    store = TaskStore()
    store.add("A", None)
    store.list().clear()
    assert len(store.list()) == 1
    store.clear()
    assert store.list() == []


def test_timestamp_utc_and_serialization() -> None:
    task = TaskStore().add("A", date(2026, 12, 31))
    assert task.created_at.tzinfo == UTC
    dumped = task.model_dump(mode="json")
    assert dumped["created_at"].endswith("Z")
    assert dumped["due_date"] == "2026-12-31"
    assert set(dumped) == {"id", "title", "due_date", "created_at"}


def test_get_task_store_is_singleton() -> None:
    assert get_task_store() is get_task_store()


def test_title_stripped() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"  # type: ignore[call-arg]


@pytest.mark.parametrize("title", ["", "   ", "x" * 201, 5, None])
def test_bad_titles(title: object) -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title=title)  # type: ignore[arg-type]


def test_title_boundary_after_trim() -> None:
    assert len(TaskCreate(title=" " + "x" * 200 + " ").title) == 200  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["2026-02-30", "31.12.2026", "2026-12-31T10:00:00", 20261231, ""])
def test_bad_due_dates(value: object) -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="x", due_date=value)  # type: ignore[arg-type]


def test_due_date_valid_and_null() -> None:
    assert TaskCreate(title="x", due_date="2026-12-31").due_date == date(  # type: ignore[arg-type,call-arg]
        2026, 12, 31
    )
    assert TaskCreate(title="x", due_date=None).due_date is None  # type: ignore[call-arg]
