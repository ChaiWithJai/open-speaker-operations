"""The Buzz demo map stays pinned to real, addressable SpeakerOps routes."""

from pathlib import Path

from pretalx_speakerops.integrations.buzz.resources import (
    AGGREGATE,
    DETAIL,
    JUDGED_ROWS,
    RESOURCES,
)

ROOT = Path(__file__).resolve().parents[1]


def routes_by_name():
    from pretalx_speakerops import urls

    return {pattern.name: str(pattern.pattern) for pattern in urls.urlpatterns}


def test_every_registered_resource_points_at_a_real_route():
    names = routes_by_name()
    missing = [link.resource for link in RESOURCES if link.route_name not in names]
    assert missing == [], f"registry references unknown routes: {missing}"


def test_every_judged_row_has_a_demo_anchor_and_statuses_are_valid():
    by_row = {row: [link for link in RESOURCES if link.judged_row == row] for row in JUDGED_ROWS}
    rows_without_anchor = [row for row, links in by_row.items() if not links]
    assert rows_without_anchor == []
    for link in RESOURCES:
        assert link.judged_row in JUDGED_ROWS, link.resource
        assert link.status in {DETAIL, AGGREGATE}, link.resource
    # The rows the demo leans on hardest must stay record-addressable.
    detail_rows = {link.judged_row for link in RESOURCES if link.status == DETAIL}
    for row in ("review-workflows", "integrations-csv", "crm-relationships", "embeds-publishing"):
        assert row in detail_rows, f"{row} lost its record-level demo anchor"


def test_speaker_audience_links_never_land_on_organiser_paths():
    routes = routes_by_name()
    for link in RESOURCES:
        if link.audience == "speaker":
            assert not routes[link.route_name].startswith("orga/"), (
                f"{link.resource} would hand a speaker thread an organiser URL"
            )


def test_demo_map_documents_every_registered_route_and_the_demo_grammar():
    doc = (ROOT / "docs" / "buzz-demo-map.md").read_text()
    missing = [name for name in {link.route_name for link in RESOURCES} if name not in doc]
    assert missing == [], f"docs/buzz-demo-map.md does not mention: {missing}"
    for beat in ("Signal", "Evidence", "Link", "Act", "Receipt"):
        assert beat in doc
