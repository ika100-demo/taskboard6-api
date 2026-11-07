"""Task request and response models."""

import re
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    StrictStr,
    StringConstraints,
    field_serializer,
    field_validator,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Title = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: Title
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, value: object) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise ValueError("due_date must be a valid date in YYYY-MM-DD form")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a valid calendar date") from exc


class Task(BaseModel):
    """A stored task."""

    id: str
    title: str
    due_date: date | None
    created_at: datetime

    @field_serializer("due_date")
    def _ser_due_date(self, value: date | None) -> str | None:
        return value.isoformat() if value is not None else None

    @field_serializer("created_at")
    def _ser_created_at(self, value: datetime) -> str:
        utc = value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
