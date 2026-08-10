import json
from pathlib import Path

from pretalx_speakerops.history_coverage import analyze_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pretalx_speakerops" / "data" / "conferences"
CONTRACT = ROOT / "pretalx_speakerops" / "data" / "conference_history_contract.json"
ISSUE_41_LEDGER = ROOT / "docs" / "issue-41-gap-closure.json"


def test_full_catalog_matches_committed_count_and_provenance_contract():
    report = analyze_catalog(CATALOG, contract=CONTRACT)

    assert report.structurally_complete
    assert (report.documents, report.series, report.editions) == (13, 13, 204)
    assert (report.talks, report.speaker_credits, report.source_identities, report.speakers) == (
        19466,
        21419,
        21355,
        14068,
    )
    assert (
        report.known_gaps,
        report.empty_editions,
        report.missing_session_formats,
        report.missing_tracks,
    ) == (115, 5, 1067, 6077)


def test_full_catalog_contract_rejects_count_or_provenance_drift():
    contract = json.loads(CONTRACT.read_text())
    contract["series"]["ai-engineer"]["talks"] += 1
    contract["series"]["gdc"]["known_gaps"] -= 1

    report = analyze_catalog(CATALOG, contract=contract)

    assert not report.structurally_complete
    assert "contract: ai-engineer talks expected 1267, observed 1266" in report.errors
    assert "contract: gdc known_gaps expected 26, observed 27" in report.errors


def test_issue_41_gap_ledger_has_no_unresolved_historical_recovery():
    ledger = json.loads(ISSUE_41_LEDGER.read_text())
    records = ledger["records"]

    assert not [row for row in records if row["disposition"] == "open_archive_recovery"]
    assert not [row for row in records if row["disposition"] == "recovered_partial"]

    watches = [row for row in records if row["disposition"] == "open_source_watch"]
    assert len(watches) == 4
    assert {row["series"] for row in watches} == {"ai-engineer"}
    assert {row["recoverability"] for row in watches} == {"future_unpublished"}

    report = analyze_catalog(CATALOG, contract=CONTRACT)
    assert ledger["post_enrichment"]["known_gap_occurrences"] == report.known_gaps
    assert ledger["post_enrichment"]["empty_edition_occurrences"] == report.empty_editions


def test_coverage_rejects_one_canonical_key_for_different_people(tmp_path):
    document = json.loads((CATALOG / "pycon.json").read_text())
    series = document["series"][0]
    series["editions"] = series["editions"][:1]
    first_talk = series["editions"][0]["talks"][0]
    first_talk["speakers"] = [
        {"name": "First Person", "canonical_key": "reused-source-id"},
        {"name": "Different Person", "canonical_key": "reused-source-id"},
    ]
    (tmp_path / "pycon.json").write_text(json.dumps(document), encoding="utf-8")

    report = analyze_catalog(tmp_path)

    assert (
        "canonical speaker key 'reused-source-id' maps to multiple normalized names: "
        "['different-person', 'first-person']"
    ) in report.errors


def test_coverage_report_names_missing_families_and_incomplete_scope(tmp_path):
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-09T12:00:00Z",
        "series": [
            {
                "slug": "pycon-us",
                "name": "PyCon US",
                "website": "https://us.pycon.org/",
                "editions": [
                    {
                        "external_key": "2026",
                        "source_url": "https://us.pycon.org/2026/schedule/talks/",
                        "source_updated_at": "2026-08-09T12:00:00Z",
                        "talks": [
                            {
                                "external_key": "one",
                                "title": "One talk",
                                "session_format": "Talk",
                                "track": "Track",
                                "source_url": "https://us.pycon.org/2026/schedule/talks/",
                                "source_updated_at": "2026-08-09T12:00:00Z",
                                "speakers": [{"name": "Speaker"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    (tmp_path / "pycon.json").write_text(json.dumps(document), encoding="utf-8")

    report = analyze_catalog(tmp_path)

    assert report.family_counts["PyCon"] == 1
    assert "Missing required conference family: AI Engineer" in report.errors
    assert report.incomplete_scopes == ["pycon-us: scope is not declared"]
    assert not report.structurally_complete


def test_coverage_report_includes_machine_auditable_known_gaps(tmp_path):
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-09T12:00:00Z",
        "series": [
            {
                "slug": "ai-engineer",
                "name": "AI Engineer",
                "website": "https://ai.engineer/",
                "source_policy": {
                    "scope": "all official schedule editions",
                    "known_gaps": [
                        {
                            "item": "nyc-2026/talks",
                            "reason": "CFP is open; no program is published yet",
                            "source_url": "https://ai.engineer/nyc",
                        }
                    ],
                },
                "editions": [
                    {
                        "external_key": "nyc-2026",
                        "source_url": "https://ai.engineer/nyc",
                        "source_updated_at": "2026-08-09T12:00:00Z",
                        "talks": [],
                    }
                ],
            }
        ],
    }
    (tmp_path / "aie.json").write_text(json.dumps(document), encoding="utf-8")

    report = analyze_catalog(tmp_path)

    assert (
        "ai-engineer/nyc-2026/talks: CFP is open; no program is published yet" in report.source_gaps
    )
    assert "ai-engineer/nyc-2026: no public talks recovered" in report.source_gaps


def test_coverage_report_rejects_malformed_known_gaps(tmp_path):
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-09T12:00:00Z",
        "series": [
            {
                "slug": "goto",
                "name": "GOTO",
                "website": "https://gotocon.com/",
                "source_policy": {
                    "scope": "all official archive editions",
                    "known_gaps": [{"item": "berlin-2018"}],
                },
                "editions": [],
            }
        ],
    }
    (tmp_path / "goto.json").write_text(json.dumps(document), encoding="utf-8")

    report = analyze_catalog(tmp_path)

    assert "goto: known gap 1 requires item and reason" in report.errors


def test_coverage_requires_exact_declaration_for_talks_without_speaker_credits(tmp_path):
    document = json.loads((CATALOG / "ai_engineer.json").read_text())
    series = document["series"][0]
    series["editions"] = [
        {
            "external_key": "declared-gap",
            "name": "Declared source gap",
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
            "location": "",
            "source_url": "https://example.com/schedule",
            "source_updated_at": "2026-08-10T01:54:00Z",
            "expected_missing_speaker_credit_count": 1,
            "talks": [
                {
                    "external_key": "uncredited",
                    "title": "Published without a speaker",
                    "session_format": "Session",
                    "track": "Program",
                    "source_url": "https://example.com/schedule",
                    "source_updated_at": "2026-08-10T01:54:00Z",
                    "speakers": [],
                }
            ],
        }
    ]
    (tmp_path / "aie.json").write_text(json.dumps(document), encoding="utf-8")

    allowed_report = analyze_catalog(tmp_path)
    assert not any("talks without speaker credit" in error for error in allowed_report.errors)

    series["editions"][0]["expected_missing_speaker_credit_count"] = 0
    (tmp_path / "aie.json").write_text(json.dumps(document), encoding="utf-8")
    report = analyze_catalog(tmp_path)

    assert not report.structurally_complete
    assert (
        "ai-engineer/declared-gap: expected 0 talks without speaker credit, observed 1"
        in report.errors
    )
