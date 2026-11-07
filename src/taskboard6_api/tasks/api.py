"""HTTP routes for tasks."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends

from .models import Task, TaskCreate
from .store import TaskStorage, get_task_store

router = APIRouter(tags=["tasks"])
logger = structlog.get_logger(__name__)

StoreDep = Annotated[TaskStorage, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate, store: StoreDep) -> Task:
    """Create a task."""
    task = store.add(body.title, body.due_date)
    logger.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: StoreDep) -> list[Task]:
    """List tasks in creation order."""
    return store.list()
