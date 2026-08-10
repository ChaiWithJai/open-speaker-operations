import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .conference_memory import (
    canonical_speaker_key,
    load_document,
    load_documents,
    source_identity_key,
)

REQUIRED_FAMILIES = {
    "AI Engineer": lambda slug: slug == "ai-engineer",
    "PyCon": lambda slug: slug.startswith("pycon"),
    "JSConf": lambda slug: slug.startswith("jsconf"),
    "GDC": lambda slug: slug == "gdc",
    "GOTO": lambda slug: slug == "goto",
    "Strange Loop": lambda slug: slug == "strange-loop",
}
COUNT_FIELDS = (
    "editions",
    "talks",
    "speaker_credits",
    "source_identities",
    "speakers",
    "known_gaps",
    "empty_editions",
    "missing_session_formats",
    "missing_tracks",
)


def _normalized_speaker_name(name):
    """Normalize a source display name without discarding non-Latin identities."""
    try:
        return canonical_speaker_key(name)
    except ValueError:
        return " ".join(name.casefold().split())


@dataclass(frozen=True)
class CoverageReport:
    documents: int
    series: int
    editions: int
    talks: int
    speaker_credits: int
    source_identities: int
    speakers: int
    known_gaps: int
    empty_editions: int
    missing_session_formats: int
    missing_tracks: int
    catalog_sha256: str
    family_counts: dict
    series_counts: dict
    incomplete_scopes: list
    source_gaps: list
    errors: list

    @property
    def structurally_complete(self):
        return not self.errors and not self.incomplete_scopes

    def as_dict(self):
        result = asdict(self)
        result["structurally_complete"] = self.structurally_complete
        return result


def _catalog_digest(documents):
    digest = hashlib.sha256()
    for path, document in documents:
        digest.update(Path(str(path)).name.encode())
        digest.update(b"\0")
        digest.update(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _contract_errors(report, contract):
    errors = []
    if contract.get("schema_version") != 1:
        errors.append("contract: schema_version must be 1")
    if report.catalog_sha256 != contract.get("catalog_sha256"):
        errors.append(
            "contract: catalog_sha256 mismatch "
            f"(expected {contract.get('catalog_sha256')}, observed {report.catalog_sha256})"
        )
    expected_totals = contract.get("totals", {})
    for field in ("documents", "series", *COUNT_FIELDS):
        observed = getattr(report, field)
        expected = expected_totals.get(field)
        if observed != expected:
            errors.append(f"contract: total {field} expected {expected}, observed {observed}")

    expected_series = contract.get("series", {})
    observed_slugs = set(report.series_counts)
    expected_slugs = set(expected_series)
    for slug in sorted(expected_slugs - observed_slugs):
        errors.append(f"contract: missing expected series {slug}")
    for slug in sorted(observed_slugs - expected_slugs):
        errors.append(f"contract: unexpected series {slug}")
    for slug in sorted(expected_slugs & observed_slugs):
        observed = report.series_counts[slug]
        expected = expected_series[slug]
        for field in COUNT_FIELDS:
            if observed.get(field) != expected.get(field):
                errors.append(
                    f"contract: {slug} {field} expected {expected.get(field)}, "
                    f"observed {observed.get(field)}"
                )
        expected_editions = expected.get("edition_keys", [])
        if observed["edition_keys"] != expected_editions:
            missing = sorted(set(expected_editions) - set(observed["edition_keys"]))
            unexpected = sorted(set(observed["edition_keys"]) - set(expected_editions))
            errors.append(
                f"contract: {slug} edition keys differ; missing={missing}, unexpected={unexpected}"
            )
    return errors


def build_contract(report):
    """Create the reviewable expectation artifact used after a source refresh."""
    return {
        "schema_version": 1,
        "catalog_sha256": report.catalog_sha256,
        "totals": {
            field: getattr(report, field) for field in ("documents", "series", *COUNT_FIELDS)
        },
        "series": report.series_counts,
    }


def analyze_catalog(source, contract=None):
    documents = list(load_documents(source))
    series_records = [
        series for _path, document in documents for series in document.get("series", [])
    ]
    family_counts = {name: 0 for name in REQUIRED_FAMILIES}
    incomplete_scopes = []
    source_gaps = []
    errors = []
    seen_series = set()
    seen_editions = set()
    seen_talks = set()
    all_speakers = set()
    all_source_identities = set()
    speaker_names_by_key = defaultdict(set)
    series_counts = {}
    edition_count = talk_count = speaker_credit_count = 0
    known_gap_count = empty_edition_count = 0
    missing_format_count = missing_track_count = 0

    for path, document in documents:
        if document.get("schema_version") != 1:
            errors.append(f"{path}: schema_version must be 1")
        if not document.get("generated_at"):
            errors.append(f"{path}: generated_at is required")

    for series in series_records:
        slug = series.get("slug", "")
        if slug in seen_series:
            errors.append(f"duplicate series {slug!r}")
        seen_series.add(slug)
        for family, matches in REQUIRED_FAMILIES.items():
            if matches(slug):
                family_counts[family] += 1
        source_policy = series.get("source_policy", {})
        scope = source_policy.get("scope", "")
        if not scope or any(
            marker in scope.casefold() for marker in ("starter", "representative", "sample")
        ):
            incomplete_scopes.append(f"{slug}: scope is {scope or 'not declared'}")
        known_gaps = source_policy.get("known_gaps", [])
        if not isinstance(known_gaps, list):
            errors.append(f"{slug}: source_policy.known_gaps must be a list")
            known_gaps = []
        known_gap_count += len(known_gaps)
        for position, gap in enumerate(known_gaps, start=1):
            if not isinstance(gap, dict):
                errors.append(f"{slug}: known gap {position} must be an object")
                continue
            item = gap.get("item", "")
            reason = gap.get("reason", "")
            if not item or not reason:
                errors.append(f"{slug}: known gap {position} requires item and reason")
                continue
            source_url = gap.get("source_url", "")
            if source_url and not source_url.startswith(("https://", "http://")):
                errors.append(f"{slug}: known gap {position} source_url must use HTTP(S)")
            source_gaps.append(f"{slug}/{item}: {reason}")
        editions = series.get("editions", [])
        if not editions:
            errors.append(f"{slug}: no editions")
        series_speakers = set()
        series_source_identities = set()
        metrics = {
            "editions": 0,
            "talks": 0,
            "speaker_credits": 0,
            "source_identities": 0,
            "speakers": 0,
            "known_gaps": len(known_gaps),
            "empty_editions": 0,
            "missing_session_formats": 0,
            "missing_tracks": 0,
            "edition_keys": [],
        }
        for edition in editions:
            edition_count += 1
            metrics["editions"] += 1
            edition_key = (slug, edition.get("external_key"))
            metrics["edition_keys"].append(edition_key[1])
            if edition_key in seen_editions:
                errors.append(f"{slug}: duplicate edition {edition_key[1]!r}")
            seen_editions.add(edition_key)
            if not edition.get("source_url") or not edition.get("source_updated_at"):
                errors.append(f"{slug}/{edition_key[1]}: missing edition provenance")
            talks = edition.get("talks", [])
            missing_credit_contexts = []
            if not talks:
                empty_edition_count += 1
                metrics["empty_editions"] += 1
                source_gaps.append(f"{slug}/{edition_key[1]}: no public talks recovered")
            for talk in talks:
                talk_count += 1
                metrics["talks"] += 1
                talk_key = (*edition_key, talk.get("external_key"))
                if talk_key in seen_talks:
                    errors.append(f"{'/'.join(str(item) for item in talk_key)}: duplicate talk")
                seen_talks.add(talk_key)
                context = "/".join(str(item) for item in talk_key)
                for field in ("external_key", "title", "source_url", "source_updated_at"):
                    if not talk.get(field):
                        errors.append(f"{context}: missing {field}")
                speakers = talk.get("speakers", [])
                speaker_credit_count += len(speakers)
                metrics["speaker_credits"] += len(speakers)
                if not speakers:
                    missing_credit_contexts.append(context)
                for position, speaker in enumerate(speakers):
                    if not isinstance(speaker, dict) or not speaker.get("name"):
                        errors.append(f"{context}: speaker credit {position + 1} requires name")
                        continue
                    key = speaker.get("canonical_key") or canonical_speaker_key(speaker["name"])
                    identity_key = source_identity_key(talk.get("external_key"), position, speaker)
                    speaker_names_by_key[key].add(_normalized_speaker_name(speaker["name"]))
                    all_speakers.add(key)
                    series_speakers.add(key)
                    all_source_identities.add((*edition_key, identity_key))
                    series_source_identities.add((edition_key[1], identity_key))
                if not talk.get("session_format"):
                    missing_format_count += 1
                    metrics["missing_session_formats"] += 1
                    source_gaps.append(f"{context}: format not published by source")
                if not talk.get("track"):
                    missing_track_count += 1
                    metrics["missing_tracks"] += 1
                    source_gaps.append(f"{context}: track not published by source")
            expected_missing_credits = edition.get("expected_missing_speaker_credit_count", 0)
            if len(missing_credit_contexts) != expected_missing_credits:
                errors.append(
                    f"{slug}/{edition_key[1]}: expected {expected_missing_credits} talks without "
                    f"speaker credit, observed {len(missing_credit_contexts)}"
                )
        metrics["speakers"] = len(series_speakers)
        metrics["source_identities"] = len(series_source_identities)
        metrics["edition_keys"] = sorted(metrics["edition_keys"])
        series_counts[slug] = metrics

    for family, count in family_counts.items():
        if not count:
            errors.append(f"Missing required conference family: {family}")
    for key, names in sorted(speaker_names_by_key.items()):
        if len(names) > 1:
            errors.append(
                f"canonical speaker key {key!r} maps to multiple normalized names: {sorted(names)}"
            )
    report = CoverageReport(
        documents=len(documents),
        series=len(series_records),
        editions=edition_count,
        talks=talk_count,
        speaker_credits=speaker_credit_count,
        source_identities=len(all_source_identities),
        speakers=len(all_speakers),
        known_gaps=known_gap_count,
        empty_editions=empty_edition_count,
        missing_session_formats=missing_format_count,
        missing_tracks=missing_track_count,
        catalog_sha256=_catalog_digest(documents),
        family_counts=family_counts,
        series_counts=series_counts,
        incomplete_scopes=sorted(incomplete_scopes),
        source_gaps=sorted(source_gaps),
        errors=sorted(errors),
    )
    if contract is None:
        return report
    contract_document = load_document(contract) if not isinstance(contract, dict) else contract
    contract_errors = _contract_errors(report, contract_document)
    return CoverageReport(**{**asdict(report), "errors": sorted(report.errors + contract_errors)})
