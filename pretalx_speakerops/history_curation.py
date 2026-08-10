import json
from dataclasses import asdict, dataclass
from pathlib import Path

from django.db import transaction

from .conference_memory import resolve_source_identity
from .models import (
    ConferenceSeries,
    HistoricalIdentityDecision,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
)


@dataclass(frozen=True)
class CurationResult:
    groups: int
    identities: int
    decisions_created: int

    def as_dict(self):
        return asdict(self)


def load_identity_decisions(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Conference identity decisions schema_version must be 1")
    groups = document.get("verified_identity_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Conference identity decisions require verified_identity_groups")
    return groups


@transaction.atomic
def apply_identity_decisions(groups, *, actor=None):
    """Apply explicit, sourced cross-edition identity decisions idempotently."""
    identity_count = 0
    decision_count = 0
    for group in groups:
        series_slug = str(group.get("series", "")).strip()
        canonical_key = str(group.get("canonical_key", "")).strip()
        reason = str(group.get("reason", "")).strip()
        evidence_url = str(group.get("evidence_url", "")).strip()
        members = group.get("members")
        if not series_slug or not canonical_key or not reason:
            raise ValueError(
                "Every verified identity group requires series, canonical_key, and reason"
            )
        if not evidence_url.startswith("https://"):
            raise ValueError("Every verified identity group requires an HTTPS evidence_url")
        if not isinstance(members, list) or len(members) < 2:
            raise ValueError("Verified identity groups must span at least two source identities")
        edition_keys = {str(member.get("edition", "")).strip() for member in members}
        if "" in edition_keys or len(edition_keys) < 2:
            raise ValueError("Verified identity groups must span at least two editions")

        series = ConferenceSeries.objects.filter(slug=series_slug).first()
        if not series:
            raise ValueError(f"Identity decision series {series_slug!r} is not imported")
        speaker = HistoricalSpeaker.objects.filter(canonical_key=canonical_key).first()
        if not speaker:
            raise ValueError(f"Identity decision speaker {canonical_key!r} is not imported")

        identities = []
        for member in members:
            edition_key = str(member.get("edition", "")).strip()
            source_key = str(member.get("source_key", "")).strip()
            if not source_key:
                raise ValueError("Identity decision members require source_key")
            try:
                identity = HistoricalSourceIdentity.objects.select_related("edition").get(
                    edition__series=series,
                    edition__external_key=edition_key,
                    source_key=source_key,
                    active=True,
                )
            except HistoricalSourceIdentity.DoesNotExist as exc:
                raise ValueError(
                    f"Identity decision member {series_slug}/{edition_key}/{source_key} "
                    "is not imported"
                ) from exc
            if identity.speaker_id != speaker.pk:
                raise ValueError(
                    f"Identity decision member {edition_key}/{source_key} does not map to "
                    f"{canonical_key!r}; use the operator relink workflow first"
                )
            identities.append(identity)

        for selected_identity in identities:
            identity_count += 1
            identity = HistoricalSourceIdentity.objects.get(pk=selected_identity.pk)
            if identity.resolution_status == HistoricalSourceIdentity.VERIFIED:
                continue
            resolve_source_identity(
                identity,
                speaker,
                actor=actor,
                action=HistoricalIdentityDecision.LINK,
                reason=reason,
                evidence_url=evidence_url,
            )
            decision_count += 1

        verified_editions = (
            HistoricalSourceIdentity.objects.filter(
                pk__in=[identity.pk for identity in identities],
                speaker=speaker,
                resolution_status=HistoricalSourceIdentity.VERIFIED,
                active=True,
            )
            .values("edition_id")
            .distinct()
            .count()
        )
        if verified_editions < 2:
            raise ValueError(f"Identity decision group {canonical_key!r} did not verify recurrence")

    return CurationResult(
        groups=len(groups), identities=identity_count, decisions_created=decision_count
    )
