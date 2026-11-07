"""Unit tests for the Database module."""

from __future__ import annotations

import time

import pytest

from taskboard6_api.db import Database, StorageUnavailableError


def test_unset_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db = Database()
    with pytest.raises(StorageUnavailableError), db.connection():
        pass
    assert db.ping() is False


def test_empty_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    db = Database()
    with pytest.raises(StorageUnavailableError), db.connection():
        pass
    assert db.ping() is False


def test_closed_port_fails_fast(unreachable_url: str) -> None:
    db = Database(unreachable_url)
    start = time.monotonic()
    with pytest.raises(StorageUnavailableError), db.connection():
        pass
    assert time.monotonic() - start < 3
    assert db.ping() is False


def test_message_has_no_password(unreachable_url: str) -> None:
    url = unreachable_url.replace("postgres@", "user:secret@")
    with pytest.raises(StorageUnavailableError) as info, Database(url).connection():
        pass
    assert "secret" not in str(info.value)


def test_reachable_pings_and_creates_schema(pg_url: str) -> None:
    db = Database(pg_url)
    assert db.ping() is True
    with db.connection() as conn:
        row = conn.execute("SELECT to_regclass('public.tasks') IS NOT NULL").fetchone()
    assert row == (True,)
