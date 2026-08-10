"""Import and query provenance-backed public conference history."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import (
    ConferenceEdition,
    ConferenceSeries,
    HistoricalIdentityDecision,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalSpeakerCredit,
    HistoricalTalk,
)

TITLE_STOPWORDS = {
    "about",
    "after",
    "before",
    "build",
    "building",
    "from",
    "into",
    "that",
    "their",
    "this",
    "using",
    "what",
    "when",
    "with",
    "your",
}
SOURCE_NOT_PROVIDED = "Not provided by source"


@dataclass(frozen=True)
class ImportResult:
    series: int = 0
    editions: int = 0
    talks: int = 0
    speakers: int = 0
    source_identities: int = 0
    deleted_talks: int = 0


@dataclass(frozen=True)
class ImportVerification:
    series: int
    editions: int
    talks: int
    speaker_credits: int
    speakers: int
    source_identities: int
    errors: list

    @property
    def complete(self):
        return not self.errors

    def as_dict(self):
        return {
            "series": self.series,
            "editions": self.editions,
            "talks": self.talks,
            "speaker_credits": self.speaker_credits,
            "speakers": self.speakers,
            "source_identities": self.source_identities,
            "errors": self.errors,
            "complete": self.complete,
        }


def _required(record, field, context):
    value = record.get(field)
    if value in (None, "", []):
        raise ValueError(f"{context} requires {field!r}")
    return value


def _source_timestamp(value):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid source_updated_at timestamp: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _source_url(record, field, context):
    value = _required(record, field, context)
    if not value.startswith("https://"):
        raise ValueError(f"{context} {field!r} must use HTTPS")
    return value


def _field_provenance(record, context):
    provenance = record.get("field_provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError(f"{context} 'field_provenance' must be an object")
    normalized = {}
    for field, evidence in provenance.items():
        if not isinstance(evidence, dict):
            raise ValueError(f"{context} field provenance for {field!r} must be an object")
        source_url = _source_url(evidence, "source_url", f"{context} field {field!r}")
        source_updated_at = _source_timestamp(
            _required(evidence, "source_updated_at", f"{context} field {field!r}")
        )
        normalized[field] = {
            **evidence,
            "source_url": source_url,
            "source_updated_at": source_updated_at.isoformat(),
        }
    return normalized


def _optional_date(record, field, context):
    value = record.get(field, "")
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise ValueError(f"{context} has invalid {field!r}: {value!r}")
    return parsed


def canonical_speaker_key(name):
    """Return a reviewable fallback identity; feeds may supply a stronger key."""
    normalized = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not normalized:
        raise ValueError("Speaker name cannot produce an identity key")
    return normalized


def source_identity_key(talk_key, position, speaker_record):
    """Return an edition-scoped source identity, never a global person identifier."""
    external_key = speaker_record.get("canonical_key")
    if external_key:
        return f"ext:{external_key}"
    return f"credit:{talk_key}:{position}"


def _normalized_identity_name(name):
    try:
        return canonical_speaker_key(name)
    except ValueError:
        return " ".join(name.casefold().split())


@transaction.atomic
def resolve_source_identity(
    source_identity,
    resolved_speaker,
    *,
    actor,
    action,
    reason,
    evidence_url,
):
    """Apply an explicit identity decision and preserve it across future imports."""
    if action not in dict(HistoricalIdentityDecision.ACTION_CHOICES):
        raise ValueError(f"Unsupported identity action: {action!r}")
    if not reason.strip():
        raise ValueError("Identity decisions require a reason")
    if not evidence_url.startswith("https://"):
        raise ValueError("Identity decisions require an HTTPS evidence URL")
    identity = HistoricalSourceIdentity.objects.select_for_update().get(pk=source_identity.pk)
    prior_speaker = identity.speaker
    affected_talk_ids = list(identity.credits.values_list("talk_id", flat=True))
    duplicate_talk = (
        HistoricalSpeakerCredit.objects.filter(
            talk_id__in=affected_talk_ids,
            speaker=resolved_speaker,
        )
        .exclude(source_identity=identity)
        .select_related("talk")
        .first()
    )
    if duplicate_talk:
        raise ValueError(
            "Identity decision would create duplicate speaker credit on talk "
            f"{duplicate_talk.talk.external_key!r}"
        )
    identity.speaker = resolved_speaker
    identity.resolution_status = HistoricalSourceIdentity.VERIFIED
    identity.save(update_fields=["speaker", "resolution_status", "updated"])
    anchor_identity = (
        HistoricalSourceIdentity.objects.filter(
            speaker=resolved_speaker,
            active=True,
        )
        .exclude(pk=identity.pk)
        .order_by("edition__date_from", "pk")
        .first()
    )
    if action in (HistoricalIdentityDecision.LINK, HistoricalIdentityDecision.RELINK) and not (
        anchor_identity
    ):
        raise ValueError("Link decisions require an active target source identity")
    if anchor_identity:
        HistoricalSourceIdentity.objects.filter(pk=anchor_identity.pk).exclude(
            resolution_status=HistoricalSourceIdentity.NEEDS_REVIEW
        ).update(resolution_status=HistoricalSourceIdentity.VERIFIED)
    HistoricalSourceIdentity.objects.filter(
        speaker=resolved_speaker,
        active=True,
        pk=identity.pk,
    ).update(resolution_status=HistoricalSourceIdentity.VERIFIED)
    identity.credits.update(speaker=resolved_speaker)
    for talk in HistoricalTalk.objects.filter(pk__in=affected_talk_ids):
        talk.speakers.set(talk.credits.values_list("speaker_id", flat=True).distinct())
    decision_version = (
        identity.decisions.aggregate(version=Max("decision_version"))["version"] or 0
    ) + 1
    return HistoricalIdentityDecision.objects.create(
        source_identity=identity,
        prior_speaker=prior_speaker,
        resolved_speaker=resolved_speaker,
        action=action,
        reason=reason.strip(),
        evidence_url=evidence_url,
        actor=actor,
        decision_version=decision_version,
    )


def find_related_talks(submission, limit=5):
    """Surface source-backed precedent for a proposal without opaque scoring."""
    speaker_keys = [
        canonical_speaker_key(name)
        for name in submission.speakers.values_list("name", flat=True)
        if name
    ]
    title_terms = [
        term
        for term in re.findall(r"[a-z0-9]+", submission.title.casefold())
        if len(term) >= 4 and term not in TITLE_STOPWORDS
    ][:6]
    query = Q()
    for term in title_terms:
        query |= Q(title__icontains=term)
    if speaker_keys:
        query |= Q(speakers__canonical_key__in=speaker_keys)
    if not query.children:
        return []
    talks = list(
        HistoricalTalk.objects.filter(query)
        .select_related("edition__series")
        .prefetch_related("credits__speaker")
        .distinct()
        .order_by("-edition__date_from", "title")[:limit]
    )
    for talk in talks:
        talk.speakerops_match_reason = (
            "returning speaker"
            if any(credit.speaker.canonical_key in speaker_keys for credit in talk.credits.all())
            else "similar title"
        )
    return talks


def _compared_distribution(aie_talks, peer_talks, field, limit=6, *, normalize_case=False):
    """Compare only labels published by a source; never manufacture missing metadata."""

    def counts(queryset):
        if normalize_case:
            return Counter(
                " ".join(value.split()).casefold()
                for value in queryset.order_by().values_list(field, flat=True)
                if value and value != SOURCE_NOT_PROVIDED
            )
        return {
            row[field]: row["count"]
            for row in queryset.order_by()
            .exclude(**{f"{field}__in": ("", SOURCE_NOT_PROVIDED)})
            .values(field)
            .annotate(count=Count("pk"))
        }

    aie_counts = counts(aie_talks)
    peer_counts = counts(peer_talks)
    labels = sorted(
        aie_counts.keys() | peer_counts.keys(),
        key=lambda label: (-(aie_counts.get(label, 0) + peer_counts.get(label, 0)), label),
    )[:limit]
    return [
        {
            "label": label.title() if normalize_case else label,
            "aie": aie_counts.get(label, 0),
            "peers": peer_counts.get(label, 0),
        }
        for label in labels
    ]


def memory_decision_support(talks):
    """Build transparent AIE-versus-peer signals from the currently filtered evidence."""
    aie_talks = talks.filter(edition__series__slug="ai-engineer")
    peer_talks = talks.exclude(edition__series__slug="ai-engineer")
    aie_summary = aie_talks.aggregate(
        talks=Count("pk"),
        editions=Count("edition", distinct=True),
        latest=Max("edition__date_from"),
    )
    peer_summary = peer_talks.aggregate(
        talks=Count("pk"),
        editions=Count("edition", distinct=True),
        latest=Max("edition__date_from"),
    )
    returning_speakers = list(
        HistoricalSpeaker.objects.filter(
            source_identities__active=True,
            source_identities__resolution_status=HistoricalSourceIdentity.VERIFIED,
            source_identities__edition__series__slug="ai-engineer",
        )
        .annotate(
            appearance_count=Count("credits__talk", distinct=True),
            edition_count=Count("source_identities__edition", distinct=True),
            latest_appearance=Max("source_identities__edition__date_from"),
        )
        .filter(edition_count__gte=2)
        .order_by("-edition_count", "-appearance_count", "name")[:6]
    )

    aie_topics = Counter(
        topic
        for topics in aie_talks.order_by().values_list("topics", flat=True)
        for topic in (topics or [])
        if topic
    )
    peer_topics = Counter(
        topic
        for topics in peer_talks.order_by().values_list("topics", flat=True)
        for topic in (topics or [])
        if topic
    )
    topic_labels = sorted(
        aie_topics.keys() | peer_topics.keys(),
        key=lambda label: (-(aie_topics[label] + peer_topics[label]), label),
    )[:6]

    return {
        "aie": aie_summary,
        "peers": peer_summary,
        "returning_speakers": returning_speakers,
        "formats": _compared_distribution(
            aie_talks, peer_talks, "session_format", normalize_case=True
        ),
        "tracks": _compared_distribution(aie_talks, peer_talks, "track"),
        "topics": [
            {"label": label, "aie": aie_topics[label], "peers": peer_topics[label]}
            for label in topic_labels
        ],
        "aie_missing_format": aie_talks.filter(
            session_format__in=("", SOURCE_NOT_PROVIDED)
        ).count(),
        "aie_missing_track": aie_talks.filter(track__in=("", SOURCE_NOT_PROVIDED)).count(),
    }


def speaker_memory_summary(speaker, talks):
    """Summarize one evidence cluster without implying verified identity or quality."""
    talks = list(talks)

    def distribution(values):
        counts = Counter(value for value in values if value and value != SOURCE_NOT_PROVIDED)
        return [
            {"label": label, "count": count}
            for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    aliases = sorted(
        {
            credit.name_at_source
            for talk in talks
            for credit in talk.credits.all()
            if credit.speaker_id == speaker.pk and credit.name_at_source
        }
    )
    dates = [talk.edition.date_from for talk in talks if talk.edition.date_from]
    formats = distribution(talk.session_format for talk in talks)
    tracks = distribution(talk.track for talk in talks)
    topics = distribution(topic for talk in talks for topic in (talk.topics or []))
    missing_format = sum(talk.session_format in ("", SOURCE_NOT_PROVIDED) for talk in talks)
    missing_track = sum(talk.track in ("", SOURCE_NOT_PROVIDED) for talk in talks)
    missing_topics = sum(not talk.topics for talk in talks)
    metadata_slots = len(talks) * 3
    published_metadata = metadata_slots - missing_format - missing_track - missing_topics
    checked = [speaker.source_updated_at]
    checked.extend(talk.source_updated_at for talk in talks)
    checked.extend(
        credit.source_updated_at
        for talk in talks
        for credit in talk.credits.all()
        if credit.speaker_id == speaker.pk
    )
    return {
        "talk_count": len(talks),
        "edition_count": len({talk.edition_id for talk in talks}),
        "series_count": len({talk.edition.series_id for talk in talks}),
        "first_appearance": min(dates, default=None),
        "latest_appearance": max(dates, default=None),
        "aliases": aliases or [speaker.name],
        "formats": formats,
        "tracks": tracks,
        "topics": topics,
        "missing_format": missing_format,
        "missing_track": missing_track,
        "missing_topics": missing_topics,
        "metadata_coverage": (
            round(100 * published_metadata / metadata_slots) if metadata_slots else None
        ),
        "source_checked": max(filter(None, checked), default=None),
    }


def conference_coverage():
    """Return family and edition coverage without treating known source gaps as data."""
    editions = ConferenceEdition.objects.annotate(
        talk_count=Count("talks", distinct=True),
        missing_format_count=Count(
            "talks",
            filter=Q(talks__session_format__in=("", SOURCE_NOT_PROVIDED)),
            distinct=True,
        ),
        missing_track_count=Count(
            "talks",
            filter=Q(talks__track__in=("", SOURCE_NOT_PROVIDED)),
            distinct=True,
        ),
        latest_talk_check=Max("talks__source_updated_at"),
    ).order_by("-date_from", "name")
    series = list(
        ConferenceSeries.objects.prefetch_related(Prefetch("editions", queryset=editions))
    )
    for item in series:
        item.speakerops_editions = list(item.editions.all())
        item.speakerops_talk_count = sum(edition.talk_count for edition in item.speakerops_editions)
        item.speakerops_missing_format = sum(
            edition.missing_format_count for edition in item.speakerops_editions
        )
        item.speakerops_missing_track = sum(
            edition.missing_track_count for edition in item.speakerops_editions
        )
        item.speakerops_empty_editions = sum(
            edition.talk_count == 0 for edition in item.speakerops_editions
        )
        item.speakerops_declared_gaps = len(item.source_policy.get("known_gaps", []))
        checks = [
            max(filter(None, (edition.source_updated_at, edition.latest_talk_check)))
            for edition in item.speakerops_editions
        ]
        item.speakerops_last_checked = max(checks, default=None)
        denominator = item.speakerops_talk_count * 2
        published_labels = denominator - (
            item.speakerops_missing_format + item.speakerops_missing_track
        )
        item.speakerops_label_coverage = (
            round(100 * published_labels / denominator) if denominator else None
        )
        for edition in item.speakerops_editions:
            edition.speakerops_last_checked = max(
                filter(None, (edition.source_updated_at, edition.latest_talk_check))
            )
            edition.speakerops_label_coverage = (
                round(
                    100
                    * (
                        edition.talk_count * 2
                        - edition.missing_format_count
                        - edition.missing_track_count
                    )
                    / (edition.talk_count * 2)
                )
                if edition.talk_count
                else None
            )
    return series


def load_document(source):
    """Load a memory document from a path or HTTPS URL."""
    source_text = str(source)
    if source_text.startswith("https://"):
        request = Request(source_text, headers={"User-Agent": "speakerops-history/1"})
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    if "://" in source_text:
        raise ValueError("Conference history imports accept local files or HTTPS URLs")
    return json.loads(Path(source_text).read_text(encoding="utf-8"))


def load_documents(source):
    """Yield one document, or every JSON document in a catalog directory."""
    source_path = Path(str(source))
    if source_path.is_dir():
        files = sorted(source_path.glob("*.json"))
        if not files:
            raise ValueError(f"No JSON documents found in {source_path}")
        for path in files:
            yield path, load_document(path)
        return
    yield source, load_document(source)


def _inventory_difference(label, expected, observed):
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if not missing and not unexpected:
        return None
    return (
        f"{label} differ: missing={missing[:5]}"
        f"{' …' if len(missing) > 5 else ''}, unexpected={unexpected[:5]}"
        f"{' …' if len(unexpected) > 5 else ''}"
    )


def _missing_inventory(label, expected, observed):
    missing = sorted(expected - observed)
    if not missing:
        return None
    return f"{label} missing={missing[:5]}{' …' if len(missing) > 5 else ''}"


def verify_imported_catalog(source):
    """Compare every imported identity key with the normalized catalog."""
    expected_series = set()
    expected_editions = set()
    expected_talks = set()
    expected_credits = set()
    expected_speakers = set()
    expected_source_identities = set()
    for _path, document in load_documents(source):
        for series in document.get("series", []):
            slug = series["slug"]
            expected_series.add(slug)
            for edition in series.get("editions", []):
                edition_key = edition["external_key"]
                expected_editions.add((slug, edition_key))
                for talk in edition.get("talks", []):
                    talk_key = talk["external_key"]
                    expected_talks.add((slug, edition_key, talk_key))
                    for position, speaker in enumerate(talk.get("speakers", [])):
                        speaker_key = speaker.get("canonical_key") or canonical_speaker_key(
                            speaker["name"]
                        )
                        identity_key = source_identity_key(talk_key, position, speaker)
                        expected_speakers.add(speaker_key)
                        expected_credits.add((slug, edition_key, talk_key, identity_key, position))
                        expected_source_identities.add(
                            (
                                slug,
                                edition_key,
                                identity_key,
                            )
                        )

    observed_series = set(ConferenceSeries.objects.values_list("slug", flat=True))
    observed_editions = set(ConferenceEdition.objects.values_list("series__slug", "external_key"))
    observed_talks = set(
        HistoricalTalk.objects.values_list(
            "edition__series__slug", "edition__external_key", "external_key"
        )
    )
    observed_credits = set(
        HistoricalSpeakerCredit.objects.values_list(
            "talk__edition__series__slug",
            "talk__edition__external_key",
            "talk__external_key",
            "source_identity__source_key",
            "position",
        )
    )
    observed_speakers = set(HistoricalSpeaker.objects.values_list("canonical_key", flat=True))
    observed_source_identities = set(
        HistoricalSourceIdentity.objects.filter(active=True).values_list(
            "edition__series__slug", "edition__external_key", "source_key"
        )
    )
    errors = [
        error
        for error in (
            _inventory_difference("series", expected_series, observed_series),
            _inventory_difference("editions", expected_editions, observed_editions),
            _inventory_difference("talks", expected_talks, observed_talks),
            _inventory_difference("speaker credits", expected_credits, observed_credits),
            # Canonical clusters are operator-owned once identities are reviewed. A
            # split may add a durable cluster, so require every source-default
            # cluster to remain present without rejecting audited operator additions.
            _missing_inventory(
                "source-default speaker clusters", expected_speakers, observed_speakers
            ),
            _inventory_difference(
                "source identities", expected_source_identities, observed_source_identities
            ),
        )
        if error
    ]
    return ImportVerification(
        series=len(observed_series),
        editions=len(observed_editions),
        talks=len(observed_talks),
        speaker_credits=len(observed_credits),
        speakers=len(observed_speakers),
        source_identities=len(observed_source_identities),
        errors=errors,
    )


@transaction.atomic
def import_document(document, *, prune=False):
    """Idempotently import a normalized document and retain source provenance."""
    if document.get("schema_version") != 1:
        raise ValueError("Conference history schema_version must be 1")

    counts = {
        "series": 0,
        "editions": 0,
        "talks": 0,
        "speakers": 0,
        "source_identities": 0,
        "deleted_talks": 0,
    }
    for series_record in _required(document, "series", "document"):
        slug = _required(series_record, "slug", "series")
        series, created = ConferenceSeries.objects.update_or_create(
            slug=slug,
            defaults={
                "name": _required(series_record, "name", f"series {slug}"),
                "website": _source_url(series_record, "website", f"series {slug}"),
                "source_policy": series_record.get("source_policy", {}),
            },
        )
        counts["series"] += int(created)

        for edition_record in _required(series_record, "editions", f"series {slug}"):
            edition_key = _required(edition_record, "external_key", f"series {slug}")
            source_updated_at = _source_timestamp(
                _required(edition_record, "source_updated_at", f"edition {edition_key}")
            )
            edition, created = ConferenceEdition.objects.update_or_create(
                series=series,
                external_key=edition_key,
                defaults={
                    "name": _required(edition_record, "name", f"edition {edition_key}"),
                    "date_from": _optional_date(
                        edition_record, "date_from", f"edition {edition_key}"
                    ),
                    "date_to": _optional_date(edition_record, "date_to", f"edition {edition_key}"),
                    "location": edition_record.get("location", ""),
                    "source_url": _source_url(
                        edition_record, "source_url", f"edition {edition_key}"
                    ),
                    "source_updated_at": source_updated_at,
                },
            )
            counts["editions"] += int(created)

            seen_talks = set()
            for talk_record in edition_record.get("talks", []):
                talk_key = _required(talk_record, "external_key", f"edition {edition_key}")
                if talk_key in seen_talks:
                    raise ValueError(f"Duplicate talk key {talk_key!r} in edition {edition_key}")
                seen_talks.add(talk_key)
                recording_url = talk_record.get("recording_url", "")
                if recording_url and not recording_url.startswith("https://"):
                    raise ValueError(f"talk {talk_key} 'recording_url' must use HTTPS")
                talk, created = HistoricalTalk.objects.update_or_create(
                    edition=edition,
                    external_key=talk_key,
                    defaults={
                        "title": _required(talk_record, "title", f"talk {talk_key}"),
                        "abstract": talk_record.get("abstract", ""),
                        "session_format": talk_record.get("session_format") or SOURCE_NOT_PROVIDED,
                        "track": talk_record.get("track") or SOURCE_NOT_PROVIDED,
                        "level": talk_record.get("level", ""),
                        "topics": talk_record.get("topics", []),
                        "recording_url": recording_url,
                        "source_url": _source_url(talk_record, "source_url", f"talk {talk_key}"),
                        "source_updated_at": _source_timestamp(
                            talk_record.get("source_updated_at")
                            or edition_record["source_updated_at"]
                        ),
                        "field_provenance": _field_provenance(talk_record, f"talk {talk_key}"),
                    },
                )
                counts["talks"] += int(created)

                speakers = []
                source_identities = []
                for position, speaker_record in enumerate(talk_record.get("speakers", [])):
                    name = _required(speaker_record, "name", f"talk {talk_key} speaker")
                    key = speaker_record.get("canonical_key") or canonical_speaker_key(name)
                    speaker_source_url = speaker_record.get("source_url")
                    if speaker_source_url and not speaker_source_url.startswith("https://"):
                        raise ValueError(f"speaker {name!r} 'source_url' must use HTTPS")
                    existing_speaker = HistoricalSpeaker.objects.filter(canonical_key=key).first()
                    if existing_speaker and _normalized_identity_name(existing_speaker.name) != (
                        _normalized_identity_name(name)
                    ):
                        raise ValueError(
                            f"Canonical speaker key {key!r} cannot map both "
                            f"{existing_speaker.name!r} and {name!r}"
                        )
                    speaker, speaker_created = HistoricalSpeaker.objects.update_or_create(
                        canonical_key=key,
                        defaults={
                            "name": name,
                            "biography": speaker_record.get("biography", ""),
                            "source_url": speaker_source_url or talk_record["source_url"],
                            "source_updated_at": _source_timestamp(
                                speaker_record.get("source_updated_at")
                                or talk_record.get("source_updated_at")
                                or edition_record["source_updated_at"]
                            ),
                        },
                    )
                    counts["speakers"] += int(speaker_created)
                    identity_key = source_identity_key(talk_key, position, speaker_record)
                    source_identity = HistoricalSourceIdentity.objects.filter(
                        edition=edition, source_key=identity_key
                    ).first()
                    if source_identity:
                        if _normalized_identity_name(source_identity.display_name) != (
                            _normalized_identity_name(name)
                        ):
                            raise ValueError(
                                f"Source identity {edition_key}/{identity_key} changed from "
                                f"{source_identity.display_name!r} to {name!r}"
                            )
                        source_identity.display_name = name
                        source_identity.source_url = speaker_source_url or talk_record["source_url"]
                        source_identity.source_updated_at = _source_timestamp(
                            speaker_record.get("source_updated_at")
                            or talk_record.get("source_updated_at")
                            or edition_record["source_updated_at"]
                        )
                        source_identity.active = True
                        source_identity.retired_at = None
                        source_identity.save(
                            update_fields=[
                                "display_name",
                                "source_url",
                                "source_updated_at",
                                "active",
                                "retired_at",
                                "updated",
                            ]
                        )
                        speaker = source_identity.speaker
                    else:
                        prior_identities = HistoricalSourceIdentity.objects.filter(
                            speaker=speaker, active=True
                        )
                        status = (
                            HistoricalSourceIdentity.LEGACY_UNVERIFIED
                            if prior_identities.exclude(edition=edition).exists()
                            else HistoricalSourceIdentity.ISOLATED
                        )
                        if status == HistoricalSourceIdentity.LEGACY_UNVERIFIED:
                            prior_identities.exclude(
                                resolution_status=HistoricalSourceIdentity.VERIFIED
                            ).update(resolution_status=HistoricalSourceIdentity.LEGACY_UNVERIFIED)
                        source_identity = HistoricalSourceIdentity.objects.create(
                            edition=edition,
                            source_key=identity_key,
                            speaker=speaker,
                            display_name=name,
                            source_url=speaker_source_url or talk_record["source_url"],
                            source_updated_at=_source_timestamp(
                                speaker_record.get("source_updated_at")
                                or talk_record.get("source_updated_at")
                                or edition_record["source_updated_at"]
                            ),
                            resolution_status=status,
                        )
                        counts["source_identities"] += 1
                    speakers.append(speaker)
                    source_identities.append(source_identity)
                    HistoricalSpeakerCredit.objects.update_or_create(
                        talk=talk,
                        speaker=speaker,
                        defaults={
                            "source_identity": source_identity,
                            "name_at_source": name,
                            "position": position,
                            "source_url": speaker_source_url or talk_record["source_url"],
                            "source_updated_at": _source_timestamp(
                                speaker_record.get("source_updated_at")
                                or talk_record.get("source_updated_at")
                                or edition_record["source_updated_at"]
                            ),
                        },
                    )
                talk.speakers.set(speakers)
                talk.credits.exclude(source_identity__in=source_identities).delete()
            if prune:
                stale = edition.talks.exclude(external_key__in=seen_talks)
                counts["deleted_talks"] += stale.count()
                stale.delete()
                HistoricalSourceIdentity.objects.filter(
                    edition=edition,
                    active=True,
                    credits__isnull=True,
                ).update(active=False, retired_at=timezone.now())

    return ImportResult(**counts)
