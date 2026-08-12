"""Queries defining the current logical synchronization state."""

from django.db.models import Exists, OuterRef

from pretalx_speakerops.models import SyncItem


def latest_failed_sync_items(event, *, target_ids=None, lock=False):
    """Return failed rows only when no newer row exists for that logical record."""
    newer = SyncItem.objects.filter(
        event=event,
        local_type=OuterRef("local_type"),
        local_id=OuterRef("local_id"),
        pk__gt=OuterRef("pk"),
    )
    query = (
        SyncItem.objects.filter(event=event, status=SyncItem.FAILED)
        .annotate(has_newer=Exists(newer))
        .filter(has_newer=False)
    )
    if target_ids is not None:
        query = query.filter(pk__in=target_ids)
    if lock:
        query = query.select_for_update()
    return query
