"""Unit tests for PostgresTaskStore."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from taskboard6_api.db import Database, StorageUnavailableError
from taskboard6_api.tasks.pg_store import PostgresTaskStore


def test_order_across_three_adds(pg_url: str, clean_db: None) -> None:
    store = PostgresTaskStore(Database(pg_url))
    added = [store.add(t, None) for t in ("A", "B", "C")]
    assert store.list() == added


def test_created_at_microsecond_roundtrip(pg_url: str, clean_db: None) -> None:
    store = PostgresTaskStore(Database(pg_url))
    task = store.add("A", date(2026, 12, 31))
    (listed,) = store.list()
    assert listed == task
    assert listed.created_at == task.created_at
    assert listed.due_date == date(2026, 12, 31)


def test_table_created_on_fresh_server(pg_factory: Any) -> None:
    server = pg_factory.start()
    store = PostgresTaskStore(Database(server.url))
    assert store.list() == []
    assert store.add("A", None).title == "A"


def test_second_store_sees_same_rows(pg_url: str, clean_db: None) -> None:
    first = PostgresTaskStore(Database(pg_url))
    added = [first.add(t, None) for t in ("A", "B")]
    assert PostgresTaskStore(Database(pg_url)).list() == added


def test_unreachable_raises_and_stores_nothing(
    unreachable_url: str, pg_url: str, clean_db: None
) -> None:
    store = PostgresTaskStore(Database(unreachable_url))
    with pytest.raises(StorageUnavailableError):
        store.add("A", None)
    with pytest.raises(StorageUnavailableError):
        store.list()
    assert PostgresTaskStore(Database(pg_url)).list() == []
