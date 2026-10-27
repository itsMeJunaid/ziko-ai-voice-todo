"""resolve_one(): exactly-one / not-found / ambiguous (PRD §5.1 clarification rule)."""

import pytest

from app.core.clock import FakeClock
from app.core.errors import Ambiguous, NotFound
from app.database.engine import session_scope
from app.database.migrate import upgrade_to_head
from app.schemas.settings import TaskSettings
from app.schemas.task import TaskCreate
from app.services.datetime_service import DateTimeService
from app.services.task_service import TaskService
from tests.conftest import START, TZ


@pytest.fixture
def svc(env):
    upgrade_to_head()
    with session_scope() as s:
        yield TaskService(s, DateTimeService(FakeClock(START), TZ), TaskSettings(timezone=TZ))


def test_resolution(svc):
    svc.create(TaskCreate(title="Finish presentation"))
    svc.create(TaskCreate(title="Rehearse presentation"))
    svc.create(TaskCreate(title="Buy milk"))
    assert svc.resolve_one("buy milk").title == "Buy milk"
    assert svc.resolve_one("Finish presentation").title == "Finish presentation"  # exact beats substring
    with pytest.raises(Ambiguous) as e:
        svc.resolve_one("presentation")
    assert len(e.value.details["candidates"]) == 2
    with pytest.raises(NotFound):
        svc.resolve_one("dentist")


def test_completed_tasks_not_resolved_by_default(svc):
    t = svc.create(TaskCreate(title="Old thing"))
    svc.complete(t.id)
    with pytest.raises(NotFound):
        svc.resolve_one("old thing")
    assert svc.find_by_title("old thing", include_completed=True)
