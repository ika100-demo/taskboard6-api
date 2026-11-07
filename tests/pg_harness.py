"""Throwaway PostgreSQL servers for tests (stdlib + PG binaries only)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess  # nosec B404
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

_MISSING = "Postgres binaries not found: run inside `devbox shell` / `devbox run test`"
_REQUIRED = ("initdb", "pg_ctl", "pg_isready", "psql")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _binaries_available() -> bool:
    return all(shutil.which(name) for name in _REQUIRED)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        args, check=True, capture_output=True, text=True, timeout=120
    )


class PgServer:
    """A throwaway Postgres server in its own temp directory."""

    def __init__(self, port: int | None = None) -> None:
        if not _binaries_available():
            pytest.fail(_MISSING)
        self.port = port if port is not None else _free_port()
        # Short path: unix socket paths are limited to ~103 chars on macOS.
        self.root = Path(tempfile.mkdtemp(prefix="pg", dir="/tmp"))  # nosec B108
        self.data = self.root / "data"
        self.url = f"postgresql://postgres@127.0.0.1:{self.port}/postgres"
        self._initialised = False

    def start(self) -> None:
        if not self._initialised:
            _run(["initdb", "-D", str(self.data), "-U", "postgres", "-A", "trust"] + ["--no-sync"])
            self._initialised = True
        opts = f"-c listen_addresses=127.0.0.1 -p {self.port} -k {self.root} -c fsync=off"
        _run(
            ["pg_ctl", "-D", str(self.data), "-l", str(self.root / "log")]
            + ["-o", opts, "-w", "start"]
        )
        deadline = time.monotonic() + 30
        while True:
            ready = subprocess.run(  # nosec B603
                ["pg_isready", "-h", "127.0.0.1", "-p", str(self.port)],
                capture_output=True,
                check=False,
            )
            if ready.returncode == 0:
                return
            if time.monotonic() > deadline:
                pytest.fail(f"Postgres on port {self.port} did not become ready")
            time.sleep(0.1)

    def stop(self) -> None:
        if not self.data.exists():
            return
        subprocess.run(  # nosec B603
            ["pg_ctl", "-D", str(self.data), "-m", "fast", "-w", "stop"],
            capture_output=True,
            check=False,
        )

    def delete(self) -> None:
        self.stop()
        shutil.rmtree(self.root, ignore_errors=True)


class PgFactory:
    """Starts extra throwaway servers and cleans them all up."""

    def __init__(self) -> None:
        self._servers: list[PgServer] = []

    def free_port(self) -> int:
        return _free_port()

    def start(self, port: int | None = None) -> PgServer:
        server = PgServer(port)
        self._servers.append(server)
        server.start()
        return server

    def cleanup(self) -> None:
        for server in self._servers:
            server.delete()
        self._servers.clear()


def _psql(url: str, sql: str) -> str:
    return _run(["psql", url, "-X", "-t", "-A", "-c", sql]).stdout.strip()


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """URL of a running throwaway Postgres (or TEST_DATABASE_URL)."""
    previous = os.environ.get("DATABASE_URL")
    server: PgServer | None = None
    try:
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            if not _binaries_available():
                pytest.fail(_MISSING)
            server = PgServer()
            server.start()
            url = server.url
        os.environ["DATABASE_URL"] = url
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        if server is not None:
            server.delete()


@pytest.fixture()
def clean_db(pg_url: str) -> None:
    """Empty the tasks table when it exists; never drop it."""
    if _psql(pg_url, "SELECT to_regclass('public.tasks') IS NOT NULL") == "t":
        _psql(pg_url, "TRUNCATE TABLE tasks RESTART IDENTITY")


@pytest.fixture()
def unreachable_url() -> str:
    """URL on a port that was just bound and released."""
    return f"postgresql://postgres@127.0.0.1:{_free_port()}/postgres"


@pytest.fixture()
def pg_factory() -> Iterator[PgFactory]:
    factory = PgFactory()
    try:
        yield factory
    finally:
        factory.cleanup()
