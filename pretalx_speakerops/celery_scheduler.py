import logging

from celery.beat import PersistentScheduler

logger = logging.getLogger(__name__)


class EvidencePersistentScheduler(PersistentScheduler):
    """Persistent Beat scheduler that records the exact broker dispatch UUID."""

    def apply_async(self, entry, producer=None, advance=True, **kwargs):
        result = super().apply_async(entry, producer=producer, advance=advance, **kwargs)
        if entry.name == "speakerops-due-speaker-reminders-daily":
            logger.info(
                "speakerops_beat_dispatch schedule=%s task_id=%s",
                entry.name,
                result.id,
            )
        return result
