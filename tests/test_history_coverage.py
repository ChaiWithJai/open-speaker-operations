import json
from pathlib import Path

from pretalx_speakerops.history_coverage import analyze_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pretalx_speakerops" / "data" / "conferences"
CONTRACT = ROOT / "pretalx_speakerops" / "data" / "conference_history_contract.json"


def test_full_catalog_matches_committed_count_and_provenance_contract():
    report = analyze_catalog(CATALOG, contract=CONTRACT)

    assert report.structurally_complete
    assert (report.documents, report.series, report.editions) == (13, 13, 199)
    assert (report.talks, report.speaker_credits, report.speakers) == (
        18432,
        20238,
        13375,
    )
    assert (
        report.known_gaps,
        report.empty_editions,
        report.missing_session_formats,
        report.missing_tracks,
    ) == (120, 9, 1067, 5590)


def test_full_catalog_contract_rejects_count_or_provenance_drift():
    contract = json.loads(CONTRACT.read_text())
    contract["series"]["ai-engineer"]["talks"] += 1
    contract["series"]["gdc"]["known_gaps"] -= 1

    report = analyze_catalog(CATALOG, contract=contract)

    assert not report.structurally_complete
    assert "contract: ai-engineer talks expected 706, observed 705" in report.errors
    assert "contract: gdc known_gaps expected 26, observed 27" in report.errors


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
