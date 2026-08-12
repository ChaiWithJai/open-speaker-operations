from types import SimpleNamespace
from unittest.mock import patch

from pretalx_speakerops.celery_scheduler import EvidencePersistentScheduler


def test_evidence_scheduler_logs_exact_reminder_dispatch_uuid(caplog):
    entry = SimpleNamespace(name="speakerops-due-speaker-reminders-daily")
    result = SimpleNamespace(id="exact-beat-dispatch-uuid")
    scheduler = object.__new__(EvidencePersistentScheduler)
    with patch.object(EvidencePersistentScheduler.__mro__[1], "apply_async", return_value=result):
        returned = scheduler.apply_async(entry, producer=object(), advance=False)
    assert returned is result
    assert (
        "speakerops_beat_dispatch schedule=speakerops-due-speaker-reminders-daily "
        "task_id=exact-beat-dispatch-uuid" in caplog.text
    )
