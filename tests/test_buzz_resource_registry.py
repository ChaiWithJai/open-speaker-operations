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
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.canonical_links import (
    COMMAND,
    CORE_ROWS,
    EXACT_RECORD,
    EXACTNESS,
    JUDGED_ROWS,
    LINK,
    PLANNED,
    RESOURCES,
)
from pretalx_speakerops.go_resolver import RESOURCE_SEP

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_KWARGS = {
    "event": "sample-event",
    "organiser": "sample-org",
    "pk": 1,
    "assignment": 1,
    "code": "ABCDEF",
    "kind": "tasks",
    "correlation": "00000000-0000-4000-8000-000000000001",
    "nonce": "00000000-0000-4000-8000-000000000002",
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
    for row in ("review-workflows", "content-production"):
        assert row in exact_link_rows, f"{row} lost its record-level GET anchor"
    # Honest gap: no organiser-facing exact submission GET exists anywhere in
    # the plugin, so abstract-management may NOT claim a record-level anchor
    # until the go/ resolver ships a real submission resource.
    assert "abstract-management" not in exact_link_rows


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
    "av-bundle",
    "sync-console",
    "speaker-import",
    "operations-dashboard",
    "embed-builder",
)


@pytest.mark.parametrize("resource", ORGANISER_CONSOLES)
def test_organiser_surfaces_open_for_chair_only(enabled_event, users, client, resource):
    link = by_resource(resource)
    url = url_for(link, event=enabled_event.slug)
    client.force_login(users["chair"])
    assert client.get(url).status_code == 200, resource
    for role in ("speaker", "reviewer"):
        client.force_login(users[role])
        assert client.get(url).status_code == 404, f"{resource} leaked to a {role}"
    client.logout()
    anonymous = client.get(url)
    assert anonymous.status_code == 302 and "login" in anonymous["Location"], (
        f"{resource} must send anonymous users to login, never render"
    )


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
    client.force_login(users["speaker"])
    presenters = by_resource("own-submission-presenters")
    assert (
        client.get(url_for(presenters, event=enabled_event.slug, code="ZZZZZX")).status_code == 404
    )
    client.logout()
    public_speaker = by_resource("public-speaker")
    assert (
        client.get(url_for(public_speaker, event=enabled_event.slug, code="ZZZZZX")).status_code
        == 404
    )


def test_assigned_reviewer_opens_a_real_review_and_a_speaker_cannot(enabled_event, users, client):
    from pretalx.submission.models import SubmissionStates

    from pretalx_speakerops.program.reviews import configure_review_rounds

    with scope(event=enabled_event):
        submission = enabled_event.submissions.first()
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
        submission.assigned_reviewers.add(users["reviewer"])
        configure_review_rounds(enabled_event)
        pk = submission.pk
    link = by_resource("review-assignment")
    url = url_for(link, event=enabled_event.slug, pk=pk)
    client.force_login(users["reviewer"])
    assert client.get(url).status_code == 200
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404, "a valid review URL leaked to a speaker"


def test_speaker_opens_their_own_submission_presenters_and_a_chair_cannot(
    enabled_event, users, client
):
    with scope(event=enabled_event):
        submission = enabled_event.submissions.first()
        submission.speakers.add(users["speaker"])
        code = submission.code
    link = by_resource("own-submission-presenters")
    url = url_for(link, event=enabled_event.slug, code=code)
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 200
    # The view is self-scoped by design: even a chair who is not a presenter
    # receives a non-disclosing 404. This is why abstract-management has no
    # organiser-facing exact submission link.
    client.force_login(users["chair"])
    assert client.get(url).status_code == 404


def test_command_endpoints_refuse_get_so_links_can_never_mutate(enabled_event, users, client):
    client.force_login(users["chair"])
    for link in RESOURCES:
        if link.interaction != COMMAND:
            continue
        response = client.get(url_for(link, event=enabled_event.slug))
        assert response.status_code == 405, (
            f"{link.resource}: command endpoints must reject GET navigation"
        )


# --- go/ resolver -----------------------------------------------------------
#
# The go/{resource}/{opaque-id} contract: durable links resolve server-side,
# authorize before they redirect, and never expose a command route as a link.


def _go_url(resource, opaque_id):
    return reverse(
        "plugins:speakerops:speakerops_go",
        kwargs={"resource": resource, "opaque_id": opaque_id},
    )


@pytest.mark.parametrize("resource", ORGANISER_CONSOLES)
def test_go_redirects_chair_to_the_exact_organiser_view(enabled_event, users, client, resource):
    link = by_resource(resource)
    slug = enabled_event.slug
    client.force_login(users["chair"])
    response = client.get(_go_url(resource, slug))
    assert response.status_code == 302, resource
    assert response["Location"] == url_for(link, event=slug), resource


def test_go_opens_only_the_speakers_real_submission_record(enabled_event, users, client):
    slug = enabled_event.slug
    with scope(event=enabled_event):
        submission, other_submission = enabled_event.submissions.order_by("pk")[:2]
        submission.speakers.add(users["speaker"])
        other_submission.speakers.add(users["reviewer"])

    presenters = by_resource("own-submission-presenters")

    client.force_login(users["speaker"])
    target = url_for(presenters, event=slug, code=submission.code)
    response = client.get(
        _go_url("own-submission-presenters", f"{slug}{RESOURCE_SEP}{submission.code}"),
        follow=True,
    )
    assert response.status_code == 200
    assert response.redirect_chain == [(target, 302)]

    # This user is a speaker at the event, so the event-level resolver may
    # redirect, but the record view must still deny a submission they do not
    # present. Following the redirect proves the record-level authorization.
    client.force_login(users["reviewer"])
    denied = client.get(
        _go_url("own-submission-presenters", f"{slug}{RESOURCE_SEP}{submission.code}"),
        follow=True,
    )
    assert denied.status_code == 404
    assert denied.redirect_chain == [(target, 302)]


def test_go_redirects_reviewer_to_reviewer_exact_record(enabled_event, users, client):
    link = by_resource("review-assignment")
    slug = enabled_event.slug
    with scope(event=enabled_event):
        submission, unassigned = enabled_event.submissions.order_by("pk")[:2]
        enabled_event.submissions.filter(pk__in=(submission.pk, unassigned.pk)).update(
            state=SubmissionStates.SUBMITTED
        )
        submission.assigned_reviewers.add(users["reviewer"])

    client.force_login(users["reviewer"])
    target = url_for(link, event=slug, pk=submission.pk)
    response = client.get(
        _go_url("review-assignment", f"{slug}{RESOURCE_SEP}{submission.pk}"),
        follow=True,
    )
    assert response.status_code == 200
    assert response.redirect_chain == [(target, 302)]

    denied_target = url_for(link, event=slug, pk=unassigned.pk)
    denied = client.get(
        _go_url("review-assignment", f"{slug}{RESOURCE_SEP}{unassigned.pk}"),
        follow=True,
    )
    assert denied.status_code == 404
    assert denied.redirect_chain == [(denied_target, 302)]


def test_go_redirects_reviewer_directly_to_round_review_queue(enabled_event, users, client):
    link = by_resource("review-queue")
    slug = enabled_event.slug
    client.force_login(users["reviewer"])
    target = url_for(link, event=slug)
    response = client.get(_go_url("review-queue", slug), follow=True)
    assert response.status_code == 200
    assert response.redirect_chain == [(target, 302)]


def test_go_redirects_speaker_to_their_own_portal_surface(enabled_event, users, client):
    with scope(event=enabled_event):
        enabled_event.submissions.first().speakers.add(users["speaker"])
    slug = enabled_event.slug
    client.force_login(users["speaker"])
    response = client.get(_go_url("speaker-checklist", slug))
    assert response.status_code == 302
    assert response["Location"] == url_for(by_resource("speaker-checklist"), event=slug)


def test_go_redirects_anonymously_for_public_outputs(enabled_event, client):
    slug = enabled_event.slug
    response = client.get(_go_url("status", slug))
    assert response.status_code == 302
    assert response["Location"] == url_for(by_resource("status"), event=slug)


def test_go_redirects_chair_to_organiser_scoped_crm(enabled_event, users, client):
    link = by_resource("crm-directory")
    client.force_login(users["chair"])
    response = client.get(_go_url("crm-directory", enabled_event.organiser.slug))
    assert response.status_code == 302
    assert response["Location"] == url_for(link, organiser=enabled_event.organiser.slug)


def test_go_never_redirects_an_unauthorized_audience(enabled_event, users, client):
    slug = enabled_event.slug
    client.force_login(users["speaker"])
    response = client.get(_go_url("abstract-console", slug))
    assert response.status_code == 404, "speaker must get a non-disclosing 404, not a redirect"
    client.logout()
    response = client.get(_go_url("abstract-console", slug))
    assert response.status_code == 404, "anonymous must get a non-disclosing 404, not a redirect"


def test_go_404s_for_unknown_resource(enabled_event, users, client):
    client.force_login(users["chair"])
    assert client.get(_go_url("does-not-exist", enabled_event.slug)).status_code == 404


def test_go_404s_for_malformed_opaque_ids(enabled_event, users, client):
    slug = enabled_event.slug
    client.force_login(users["chair"])
    assert client.get(_go_url("abstract-console", f"{slug}{RESOURCE_SEP}extra")).status_code == 404
    bad_pk = _go_url("review-assignment", f"{slug}{RESOURCE_SEP}not-an-int")
    assert client.get(bad_pk).status_code == 404


def test_go_never_exposes_a_command_route_as_a_link(enabled_event, users, client):
    slug = enabled_event.slug
    client.force_login(users["chair"])
    for link in RESOURCES:
        if link.interaction != COMMAND:
            continue
        parts = "".join(f"{RESOURCE_SEP}{SAMPLE_KWARGS[name]}" for name in link.url_kwargs[1:])
        opaque_id = f"{slug}{parts}"
        assert client.get(_go_url(link.resource, opaque_id)).status_code == 404, link.resource
