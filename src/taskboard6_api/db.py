"""PostgreSQL access: bounded timeouts, lazy schema bootstrap, readiness ping."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

logger = logging.getLogger(__name__)

_SCHEMA_LOCK_KEY = 7302002

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    seq        bigserial   PRIMARY KEY,
    id         text        NOT NULL UNIQUE,
    title      text        NOT NULL,
    due_date   date        NULL,
    created_at timestamptz NOT NULL
)
"""


class StorageUnavailableError(Exception):
    """The task database cannot be reached or used (message never holds credentials)."""


class Database:
    """Connection factory for the task database."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _resolve_url(self) -> str:
        url = self._url or os.environ.get("DATABASE_URL")
        if not url:
            raise StorageUnavailableError("DATABASE_URL is not set")
        return url

    def _connect(self, statement_timeout_ms: int) -> psycopg.Connection:
        url = self._resolve_url()
        try:
            return psycopg.connect(
                url,
                connect_timeout=2,
                options=f"-c statement_timeout={statement_timeout_ms}",
                keepalives=1,
                keepalives_idle=5,
                keepalives_interval=2,
                keepalives_count=2,
            )
        except psycopg.OperationalError as exc:
            raise StorageUnavailableError(str(exc)) from exc

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
                conn.execute(_SCHEMA_DDL)
            self._schema_ready = True

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        conn = self._connect(2000)
        try:
            try:
                self._ensure_schema(conn)
                yield conn
                conn.commit()
            except psycopg.OperationalError as exc:
                conn.rollback()
                raise StorageUnavailableError(str(exc)) from exc
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            conn = self._connect(1000)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("database ping failed: %s", exc)
            return False
        return True
