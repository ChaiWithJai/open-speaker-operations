"""The Buzz demo map stays pinned to real, addressable, role-safe routes.

Static checks prove the registry matches the URL surface exactly; the
database-backed checks exercise the seeded role matrix over HTTP: intended
audiences reach their surfaces, unauthorized roles get non-disclosing 404s,
stale identifiers fail safely, and command endpoints refuse GET so a shared
link can never mutate state.
"""

import re
from pathlib import Path

import pytest
from django.urls import reverse
from django_scopes import scope

from pretalx_speakerops.integrations.buzz.resources import (
    COMMAND,
    CORE_ROWS,
    EXACT_RECORD,
    EXACTNESS,
    JUDGED_ROWS,
    LINK,
    PLANNED,
    RESOURCES,
)

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_KWARGS = {
    "event": "sample-event",
    "organiser": "sample-org",
    "pk": 1,
    "assignment": 1,
    "code": "ABCDEF",
    "kind": "tasks",
}


def routes_by_name():
    from pretalx_speakerops import urls

    return {pattern.name: str(pattern.pattern) for pattern in urls.urlpatterns}


def url_for(link, **overrides):
    kwargs = {name: overrides.get(name, SAMPLE_KWARGS[name]) for name in link.url_kwargs}
    return reverse(f"plugins:speakerops:{link.route_name}", kwargs=kwargs)


def by_resource(resource):
    return next(link for link in RESOURCES if link.resource == resource)


# --- static contract -------------------------------------------------------


def test_every_registered_resource_matches_a_real_route_and_its_parameters():
    routes = routes_by_name()
    for link in RESOURCES:
        assert link.route_name in routes, f"unknown route: {link.resource}"
        pattern_params = set(re.findall(r"<(?:[^:>]+:)?([^>]+)>", routes[link.route_name]))
        assert pattern_params == set(link.url_kwargs), (
            f"{link.resource}: declared kwargs {link.url_kwargs} != route "
            f"parameters {sorted(pattern_params)}"
        )


def test_every_registered_resource_reverses_with_its_declared_kwargs():
    for link in RESOURCES:
        assert url_for(link).startswith("/"), link.resource


def test_registry_hygiene_rows_covered_commands_excluded_nothing_implemented():
    for link in RESOURCES:
        assert link.judged_row in JUDGED_ROWS, link.resource
        assert link.exactness in EXACTNESS, link.resource
        assert link.interaction in {LINK, COMMAND}, link.resource
        assert link.demo_status == PLANNED, (
            f"{link.resource}: nothing may claim implemented until a real end-to-end demo exists"
        )
    # Coverage counts shareable GET links only; a POST command is not a demo
    # anchor a Buzz message could hand to a human.
    link_rows = {link.judged_row for link in RESOURCES if link.interaction == LINK}
    assert set(JUDGED_ROWS) <= link_rows
    # CRM is beyond the judging matrix and never substitutes for core coverage.
    assert "crm-relationships" not in CORE_ROWS
    exact_link_rows = {
        link.judged_row
        for link in RESOURCES
        if link.interaction == LINK and link.exactness == EXACT_RECORD
    }
    for row in ("review-workflows", "abstract-management", "content-production"):
        assert row in exact_link_rows, f"{row} lost its record-level GET anchor"


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


# --- seeded role matrix over HTTP ------------------------------------------


@pytest.fixture
def enabled_event(event):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
    return event


ORGANISER_CONSOLES = (
    "cfp-routing-console",
    "abstract-console",
    "program-decisions",
    "agenda-release",
    "content-console",
    "sync-console",
    "speaker-import",
    "operations-dashboard",
    "embed-builder",
)


@pytest.mark.parametrize("resource", ORGANISER_CONSOLES)
def test_organiser_surfaces_open_for_chair_and_404_for_speaker(
    enabled_event, users, client, resource
):
    link = by_resource(resource)
    url = url_for(link, event=enabled_event.slug)
    client.force_login(users["chair"])
    assert client.get(url).status_code == 200, resource
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404, f"{resource} leaked to a speaker"


@pytest.mark.parametrize("kind", ["conflicts", "tasks"])
def test_drilldowns_open_for_chair_and_404_for_speaker(enabled_event, users, client, kind):
    link = by_resource("conflicts-drilldown")
    url = url_for(link, event=enabled_event.slug, kind=kind)
    client.force_login(users["chair"])
    assert client.get(url).status_code == 200
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("resource", ["review-queue", "conference-memory"])
def test_reviewer_surfaces_open_for_reviewer_and_404_for_speaker(
    enabled_event, users, client, resource
):
    link = by_resource(resource)
    url = url_for(link, event=enabled_event.slug)
    client.force_login(users["reviewer"])
    assert client.get(url).status_code == 200, resource
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404, f"{resource} leaked to a speaker"


@pytest.mark.parametrize("resource", ["speaker-checklist", "speaker-profile"])
def test_speaker_portal_surfaces_open_for_the_speaker(enabled_event, users, client, resource):
    with scope(event=enabled_event):
        submission = enabled_event.submissions.first()
        submission.speakers.add(users["speaker"])
    link = by_resource(resource)
    client.force_login(users["speaker"])
    assert client.get(url_for(link, event=enabled_event.slug)).status_code == 200, resource


@pytest.mark.parametrize("resource", ["cfp-public-guide", "status"])
def test_public_surfaces_render_anonymously(enabled_event, client, resource):
    link = by_resource(resource)
    assert client.get(url_for(link, event=enabled_event.slug)).status_code == 200, resource


STALE_ID_LINKS = (
    "review-assignment",
    "round-review-assignment",
    "conference-speaker",
    "evidence-file",
)


@pytest.mark.parametrize("resource", STALE_ID_LINKS)
def test_stale_or_deleted_identifiers_fail_safely_with_404(enabled_event, users, client, resource):
    link = by_resource(resource)
    url = url_for(link, event=enabled_event.slug, pk=999999, assignment=999999)
    client.force_login(users["chair" if link.audience == "organiser" else "reviewer"])
    response = client.get(url)
    assert response.status_code == 404, f"{resource} must 404, not error, on a stale ID"


def test_stale_public_and_submission_codes_fail_safely(enabled_event, users, client):
    client.force_login(users["chair"])
    presenters = by_resource("submission-presenters")
    assert (
        client.get(url_for(presenters, event=enabled_event.slug, code="ZZZZZX")).status_code == 404
    )
    client.logout()
    public_speaker = by_resource("public-speaker")
    assert (
        client.get(url_for(public_speaker, event=enabled_event.slug, code="ZZZZZX")).status_code
        == 404
    )


def test_command_endpoints_refuse_get_so_links_can_never_mutate(enabled_event, users, client):
    client.force_login(users["chair"])
    for link in RESOURCES:
        if link.interaction != COMMAND:
            continue
        response = client.get(url_for(link, event=enabled_event.slug))
        assert response.status_code == 405, (
            f"{link.resource}: command endpoints must reject GET navigation"
        )
