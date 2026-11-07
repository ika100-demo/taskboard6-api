"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pg_harness import clean_db, pg_factory, pg_url, unreachable_url  # noqa: F401

from taskboard6_api.main import app


@pytest.fixture()
def client(pg_url: str, clean_db: None) -> TestClient:  # noqa: F811
    """A TestClient for the FastAPI application, on a clean database."""
    return TestClient(app)
