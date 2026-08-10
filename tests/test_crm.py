import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Organiser
from pretalx.person.models import SpeakerProfile

from pretalx_speakerops.models import (
    CRMContact,
    CRMEventLink,
    CRMOutreachLog,
    CRMPipelineCard,
    CRMPipelineHistory,
    CRMSegment,
    HistoricalSpeaker,
)

pytestmark = pytest.mark.django_db


def _url(event):
    return reverse("plugins:speakerops:speakerops_crm", kwargs={"event": event.slug})


def _org_url(event):
    return reverse(
        "plugins:speakerops:speakerops_crm_org",
        kwargs={"organiser": event.organiser.slug},
    )


def test_crm_organisation_route_accepts_posts(client, event, users):
    client.force_login(users["chair"])
    url = _org_url(event)

    response = client.post(
        url,
        {
            "action": "save_contact",
            "name": "Morgan Reyes",
            "email": "morgan@example.org",
            "company": "Signal Stage",
            "job_title": "Program Director",
            "tags": "Keynote",
        },
    )
    assert response.status_code == 302
    assert response.url == url
    contact = CRMContact.objects.get(organiser=event.organiser, email="morgan@example.org")
    assert contact.pipeline_card.stage == CRMPipelineCard.PROSPECT

    response = client.post(
        url,
        {
            "action": "move_stage",
            "contact_id": contact.pk,
            "stage": CRMPipelineCard.CONTACTED,
            "note": "Reached out from the organization workspace.",
        },
    )
    assert response.status_code == 302
    contact.refresh_from_db()
    assert contact.pipeline_card.stage == CRMPipelineCard.CONTACTED
    assert CRMPipelineHistory.objects.filter(card=contact.pipeline_card).count() == 1


def test_crm_contact_filters_pipeline_handoff_and_outreach_round_trip(client, event, users):
    client.force_login(users["chair"])
    url = _url(event)

    response = client.post(
        url,
        {
            "action": "save_contact",
            "name": "Taylor Kim",
            "email": "taylor@example.org",
            "company": "Vector Labs",
            "job_title": "Principal Engineer",
            "headshot_url": "https://example.org/taylor.jpg",
            "biography": "Builds reliable model platforms.",
            "tags": "AI, Keynote, AI",
            "internal_notes": "Warm introduction from the research team.",
        },
    )
    assert response.status_code == 302
    contact = CRMContact.objects.get(organiser=event.organiser, email="taylor@example.org")
    assert contact.tags == ["AI", "Keynote"]
    assert contact.pipeline_card.stage == CRMPipelineCard.PROSPECT

    response = client.get(_org_url(event))
    assert response.status_code == 200
    assert response.context["event"].organiser == event.organiser
    assert b"Organization speaker CRM" in response.content

    response = client.get(
        url,
        {"q": "taylor@", "company": "Vector Labs", "job_title": "Principal Engineer"},
    )
    assert response.status_code == 200
    assert response.context["result_count"] == 1
    assert b"Taylor Kim" in response.content
    landmark_names = re.findall(rb'<nav[^>]*aria-label="([^"]+)"', response.content)
    assert b"Speaker Operations workflow navigation" in landmark_names
    assert len(landmark_names) == len(set(landmark_names))

    response = client.post(
        url,
        {
            "action": "move_stage",
            "contact_id": contact.pk,
            "stage": CRMPipelineCard.INTERESTED,
            "note": "Asked for event dates.",
        },
    )
    assert response.status_code == 302
    contact.pipeline_card.refresh_from_db()
    assert contact.pipeline_card.stage == CRMPipelineCard.INTERESTED
    history = CRMPipelineHistory.objects.get(card=contact.pipeline_card)
    assert (history.from_stage, history.to_stage) == ("prospect", "interested")
    assert history.actor == users["chair"]

    response = client.post(
        f"{url}?company=Vector%20Labs",
        {
            "action": "save_segment",
            "segment_name": "Vector prospects",
            "contacts": [contact.pk],
        },
    )
    assert response.status_code == 302
    segment = CRMSegment.objects.get(organiser=event.organiser, name="Vector prospects")
    assert list(segment.contacts.all()) == [contact]
    assert segment.filter_definition == {"company": "Vector Labs"}

    response = client.post(
        url,
        {
            "action": "log_outreach",
            "contacts": [contact.pk],
            "subject": "{{ name }} — {{ event }} invitation",
            "body": "Hi {{name}}, your work at {{ company }} fits {{event}}.",
        },
    )
    assert response.status_code == 302
    outreach = CRMOutreachLog.objects.get(contact=contact)
    assert outreach.subject == f"Taylor Kim — {event.name} invitation"
    assert "Vector Labs" in outreach.rendered_body
    assert outreach.actor == users["chair"]

    response = client.post(url, {"action": "add_to_event", "contact_id": contact.pk})
    assert response.status_code == 302
    link = CRMEventLink.objects.get(contact=contact, event=event)
    assert link.user.email == contact.email
    with scope(event=event):
        profile = SpeakerProfile.objects.get(event=event, user=link.user)
    assert str(profile.biography) == contact.biography


def test_crm_csv_validation_explicit_merge_and_organiser_isolation(client, event, users):
    source = HistoricalSpeaker.objects.create(
        canonical_key="taylor-kim",
        name="Taylor Kim (sourced)",
        biography="Immutable sourced biography.",
        source_url="https://example.org/source/taylor",
        source_updated_at=timezone.now(),
    )
    primary = CRMContact.objects.create(
        organiser=event.organiser,
        source_speaker=source,
        name="Taylor Kim",
        email="taylor@example.org",
        company="Vector Labs",
        tags=["returning"],
    )
    CRMPipelineCard.objects.create(organiser=event.organiser, contact=primary)

    other_organiser = Organiser.objects.create(name="Other Org", slug="other-org")
    foreign = CRMContact.objects.create(
        organiser=other_organiser,
        name="Private Other Contact",
        email="private@other.example.org",
    )
    foreign_card = CRMPipelineCard.objects.create(organiser=other_organiser, contact=foreign)

    client.force_login(users["chair"])
    url = _url(event)
    response = client.post(
        url,
        {
            "action": "import_csv",
            "csv_file": SimpleUploadedFile(
                "contacts.csv",
                (
                    "Full Name,Email Address,Organization,Title,Photo URL,Bio,Labels\n"
                    "Taylor K.,taylor@example.org,Vector Labs,CTO,"
                    "https://example.org/taylor-new.jpg,Operator biography,AI;alumni\n"
                ).encode(),
                content_type="text/csv",
            ),
        },
    )
    assert response.status_code == 302
    matches = CRMContact.objects.filter(
        organiser=event.organiser, email__iexact="taylor@example.org", merged_into__isnull=True
    )
    assert matches.count() == 2
    duplicate = matches.exclude(pk=primary.pk).get()
    assert duplicate.company == "Vector Labs"
    assert duplicate.job_title == "CTO"
    assert duplicate.tags == ["AI", "alumni"]

    segment = CRMSegment.objects.create(organiser=event.organiser, name="Imported leads")
    segment.contacts.add(duplicate)
    duplicate.pipeline_card.stage = CRMPipelineCard.CONTACTED
    duplicate.pipeline_card.save()
    CRMPipelineHistory.objects.create(
        card=duplicate.pipeline_card,
        from_stage="prospect",
        to_stage="contacted",
        note="Imported follow-up",
        actor=users["chair"],
    )
    response = client.post(
        url,
        {"action": "merge", "primary_id": primary.pk, "duplicate_id": duplicate.pk},
    )
    assert response.status_code == 302
    duplicate.refresh_from_db()
    primary.refresh_from_db()
    assert duplicate.merged_into == primary
    assert primary.job_title == "CTO"
    assert set(primary.tags) == {"returning", "AI", "alumni"}
    assert segment.contacts.filter(pk=primary.pk).exists()
    assert CRMPipelineHistory.objects.filter(card=primary.pipeline_card).exists()
    source.refresh_from_db()
    assert source.name == "Taylor Kim (sourced)"
    assert source.biography == "Immutable sourced biography."

    response = client.get(url)
    assert response.status_code == 200
    assert b"Private Other Contact" not in response.content
    response = client.post(
        url,
        {
            "action": "move_stage",
            "contact_id": foreign.pk,
            "stage": CRMPipelineCard.CONFIRMED,
        },
    )
    assert response.status_code == 302
    foreign_card.refresh_from_db()
    assert foreign_card.stage == CRMPipelineCard.PROSPECT


def test_crm_rejects_invalid_csv_atomically(client, event, users):
    client.force_login(users["chair"])
    response = client.post(
        _url(event),
        {
            "action": "import_csv",
            "csv_file": SimpleUploadedFile(
                "invalid.csv",
                b"name,email\nGood,good@example.org\nNo Email,not-an-email\n",
                content_type="text/csv",
            ),
        },
    )
    assert response.status_code == 302
    assert CRMContact.objects.filter(organiser=event.organiser).count() == 0


def test_sourced_contact_without_email_explains_and_blocks_event_handoff(client, event, users):
    source = HistoricalSpeaker.objects.create(
        canonical_key="source-without-email",
        name="Source Without Email",
        source_url="https://example.org/schedule/source-without-email",
        source_updated_at=timezone.now(),
    )
    contact = CRMContact.objects.create(
        organiser=event.organiser,
        source_speaker=source,
        name=source.name,
        email="",
    )
    CRMPipelineCard.objects.create(organiser=event.organiser, contact=contact)
    client.force_login(users["chair"])
    url = _url(event)

    page = client.get(url, {"q": contact.name})

    assert page.status_code == 200
    assert b"This sourced record did not publish an email" in page.content
    assert b"will not infer or invent contact data" in page.content
    assert f"#edit-email-{contact.pk}".encode() in page.content
    assert b"Add without re-entry" not in page.content

    blocked = client.post(
        url,
        {"action": "add_to_event", "contact_id": contact.pk},
        follow=True,
    )

    assert blocked.status_code == 200
    assert b"No contact data was inferred or invented" in blocked.content
    assert not CRMEventLink.objects.filter(contact=contact, event=event).exists()


def test_org_crm_requires_manager_and_login(client, event, users):
    url = _org_url(event)
    assert client.get(url).status_code == 302
    client.force_login(users["reviewer"])
    assert client.get(url).status_code in (403, 404)


def test_org_crm_route_supports_mutations_without_event_slug(client, event, users):
    """SBEK CRM-S1 enters through the organisation URL and posts forms there."""

    client.force_login(users["chair"])
    url = _org_url(event)

    response = client.post(
        url,
        {
            "action": "save_contact",
            "name": "Jordan Regression",
            "email": "jordan-regression@example.org",
            "company": "AIE",
            "job_title": "Program operator",
            "tags": "alumni, AI",
            "internal_notes": "Organisation-route mutation regression.",
        },
    )

    assert response.status_code == 302
    assert response.url == url
    contact = CRMContact.objects.get(
        organiser=event.organiser,
        email="jordan-regression@example.org",
    )
    assert contact.tags == ["AI", "alumni"]

    response = client.post(
        url,
        {
            "action": "move_stage",
            "contact_id": contact.pk,
            "stage": CRMPipelineCard.INTERESTED,
            "note": "Moved from the canonical organisation route.",
        },
    )

    assert response.status_code == 302
    contact.pipeline_card.refresh_from_db()
    assert contact.pipeline_card.stage == CRMPipelineCard.INTERESTED
    assert contact.pipeline_card.history.get().note == (
        "Moved from the canonical organisation route."
    )
