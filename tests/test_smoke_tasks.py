"""Smoke tests for spec 001 (AC-001.1, AC-001.6); they reach the service only by URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


@pytest.mark.smoke
def test_ac_001_6_list_tasks_returns_json_array(smoke_base_url: str) -> None:  # AC-001.6
    with urllib.request.urlopen(smoke_base_url + "/tasks", timeout=10) as response:
        assert response.status == 200
        assert isinstance(json.load(response), list)


@pytest.mark.smoke
@pytest.mark.writes
def test_ac_001_1_create_task_returns_201(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    request = urllib.request.Request(  # noqa: S310
        smoke_base_url + "/tasks",
        data=json.dumps({"title": title}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        assert response.status == 201
        body = json.load(response)
    assert isinstance(body["id"], str)
    assert body["title"] == title
    assert body["due_date"] is None
    assert body["created_at"].endswith("Z")
