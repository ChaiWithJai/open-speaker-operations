import re

import pytest
from bs4 import BeautifulSoup
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_scopes import scope, scopes_disabled
from pretalx.event.models import Event, Organiser
from pretalx.person.models import SpeakerProfile, User

from pretalx_speakerops.models import (
    ConferenceEdition,
    ConferenceSeries,
    CRMContact,
    CRMEventLink,
    CRMOutreachLog,
    CRMPipelineCard,
    CRMPipelineHistory,
    CRMSegment,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalSpeakerCredit,
    HistoricalTalk,
)

pytestmark = pytest.mark.django_db


def _url(event):
    return reverse("plugins:speakerops:speakerops_crm", kwargs={"event": event.slug})


def _org_url(event):
    return reverse(
        "plugins:speakerops:speakerops_crm_org",
        kwargs={"organiser": event.organiser.slug},
    )


def _selected_url(url, contact):
    return f"{url}?contact={contact.pk}#crm-contact-{contact.pk}"


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
    contact = CRMContact.objects.get(organiser=event.organiser, email="morgan@example.org")
    assert response.url == _selected_url(url, contact)
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
    assert response.url == _selected_url(url, contact)
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
    assert b'aria-label="CRM section navigation"' in response.content
    assert b"1 of 1 contacts shown" in response.content
    assert b"Active filters:" in response.content
    assert b"speakerops-crm-pipeline" in response.content
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
    assert response.url == f"{url}?segment={segment.pk}#crm-directory-title"
    assert list(segment.contacts.all()) == [contact]
    assert segment.filter_definition == {"company": "Vector Labs"}

    selected_segment = client.get(response.url)
    assert selected_segment.status_code == 200
    assert selected_segment.context["filters"]["segment"] == str(segment.pk)
    assert b"Saved segment selected" in selected_segment.content

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
                    "Taylor Kim,taylor.alt@example.org,Vector Labs,CTO,"
                    "https://example.org/taylor-new.jpg,Operator biography,AI;alumni\n"
                ).encode(),
                content_type="text/csv",
            ),
        },
    )
    assert response.status_code == 302
    matches = CRMContact.objects.filter(
        organiser=event.organiser, name__iexact="Taylor Kim", merged_into__isnull=True
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


def test_crm_csv_exact_email_is_idempotent_and_near_name_requires_explicit_merge(
    client, event, users
):
    client.force_login(users["chair"])
    url = _url(event)

    def upload_csv(content):
        return client.post(
            url,
            {
                "action": "import_csv",
                "csv_file": SimpleUploadedFile(
                    "contacts.csv",
                    content.encode(),
                    content_type="text/csv",
                ),
            },
            follow=True,
        )

    content = (
        "name,email,company,job_title,biography,tags\n"
        "Marcus Okafor, MARCUS@EXAMPLE.ORG ,Continuity Labs,Staff Engineer,"
        "Builds durable event systems.,returning;platform\n"
    )
    first = upload_csv(content)
    assert first.status_code == 200
    assert b"1 created, 0 updated, 0 unchanged" in first.content
    contact = CRMContact.objects.get(
        organiser=event.organiser, email="marcus@example.org", merged_into__isnull=True
    )
    assert contact.tags == ["platform", "returning"]

    second = upload_csv(content)
    assert second.status_code == 200
    assert b"0 created, 0 updated, 1 unchanged" in second.content
    assert (
        CRMContact.objects.filter(
            organiser=event.organiser,
            email__iexact="marcus@example.org",
            merged_into__isnull=True,
        ).count()
        == 1
    )

    changed = upload_csv(
        "name,email,company,job_title,biography,tags\n"
        "Marcus Okafor,marcus@example.org,Continuity Labs,Principal Engineer,,\n"
    )
    assert b"0 created, 1 updated, 0 unchanged" in changed.content
    contact.refresh_from_db()
    assert contact.job_title == "Principal Engineer"
    assert contact.biography == "Builds durable event systems."
    assert contact.tags == ["platform", "returning"]

    near_duplicate = upload_csv(
        "name,email,company\nMarcus Okafor,marcus.other@example.org,Other Labs\n"
    )
    assert b"1 created, 0 updated, 0 unchanged" in near_duplicate.content
    assert b"Flagged 1 possible name duplicate" in near_duplicate.content
    assert (
        CRMContact.objects.filter(
            organiser=event.organiser, name__iexact="Marcus Okafor", merged_into__isnull=True
        ).count()
        == 2
    )
    assert b"Duplicate review" in near_duplicate.content


def test_crm_event_handoff_is_permission_scoped_and_visible_in_target_speaker_roster(
    client, event, users
):
    target_slug = f"{event.slug}-target"
    sibling_slug = f"{event.slug}-private"
    with scopes_disabled():
        for slug, name in ((target_slug, "DevFlow Conf 2027"), (sibling_slug, "Private Summit")):
            Event.objects.create(
                organiser=event.organiser,
                slug=slug,
                name=name,
                date_from=event.date_from,
                date_to=event.date_to,
                timezone=event.timezone,
                email=f"program@{slug}.example.org",
                locale="en",
                locale_array="en",
                is_public=False,
                plugins=["pretalx_speakerops"],
            )
    target = Event.objects.get(slug=target_slug)
    sibling = Event.objects.get(slug=sibling_slug)
    chair_team = users["chair"].teams.get(organiser=event.organiser)
    chair_team.limit_events.add(target)

    marcus = User.objects.create_user(
        email="marcus@example.org", name="Marcus Okafor", password="test-password"
    )
    contact = CRMContact.objects.create(
        organiser=event.organiser,
        name=marcus.name,
        email=marcus.email,
        biography="Builds durable event systems and practical program handoffs.",
    )
    CRMPipelineCard.objects.create(organiser=event.organiser, contact=contact)
    blocked_contact = CRMContact.objects.create(
        organiser=event.organiser,
        name="Private Candidate",
        email="private-candidate@example.org",
        biography="Must not cross the permission boundary.",
    )
    CRMPipelineCard.objects.create(organiser=event.organiser, contact=blocked_contact)

    client.force_login(users["chair"])
    page = client.get(_url(event), {"contact": contact.pk})
    assert page.status_code == 200
    assert set(page.context["organiser_events"]) == {target, event}
    assert str(sibling.name).encode() not in page.content

    blocked = client.post(
        _url(event),
        {
            "action": "add_to_event",
            "contact_id": blocked_contact.pk,
            "target_event": sibling.pk,
        },
        follow=True,
    )
    assert blocked.status_code == 200
    assert b"cannot manage the selected target event" in blocked.content
    blocked_contact.refresh_from_db()
    assert blocked_contact.email == "private-candidate@example.org"
    assert not User.objects.filter(email__iexact=blocked_contact.email).exists()
    assert not CRMEventLink.objects.filter(contact=blocked_contact, event=sibling).exists()
    with scope(event=sibling):
        assert not SpeakerProfile.objects.filter(event=sibling).exists()

    handed_off = client.post(
        _url(event),
        {"action": "add_to_event", "contact_id": contact.pk, "target_event": target.pk},
        follow=True,
    )
    assert handed_off.status_code == 200
    assert b"Added Marcus Okafor to DevFlow Conf 2027 without re-keying" in handed_off.content
    link = CRMEventLink.objects.get(contact=contact, event=target)
    assert link.user == marcus
    with scope(event=target):
        profile = SpeakerProfile.objects.get(event=target, user=marcus)
        assert str(profile.biography) == contact.biography

    roster = client.get(
        reverse("plugins:speakerops:speakerops_speakers", kwargs={"event": target.slug})
    )
    assert roster.status_code == 200
    assert b"Marcus Okafor" in roster.content
    assert contact.biography.encode() in roster.content
    assert b"Private Candidate" not in roster.content


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
    contact = CRMContact.objects.get(
        organiser=event.organiser,
        email="jordan-regression@example.org",
    )
    assert response.url == _selected_url(url, contact)
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
    assert response.url == _selected_url(url, contact)
    contact.pipeline_card.refresh_from_db()
    assert contact.pipeline_card.stage == CRMPipelineCard.INTERESTED
    assert contact.pipeline_card.history.get().note == (
        "Moved from the canonical organisation route."
    )


def test_crm_surfaces_live_program_memory_and_verified_recurrence(client, event, users):
    now = timezone.now()
    series = ConferenceSeries.objects.create(
        slug="ai-engineer",
        name="AI Engineer",
        website="https://example.org",
        source_policy={"authority": "published program"},
    )
    speaker = HistoricalSpeaker.objects.create(
        canonical_key="returning-builder",
        name="Returning Builder",
        source_url="https://example.org/speakers/returning-builder",
        source_updated_at=now,
    )
    for year in (2025, 2026):
        edition = ConferenceEdition.objects.create(
            series=series,
            external_key=str(year),
            name=f"AI Engineer {year}",
            source_url=f"https://example.org/{year}",
            source_updated_at=now,
        )
        identity = HistoricalSourceIdentity.objects.create(
            edition=edition,
            source_key=f"speaker-{year}",
            speaker=speaker,
            display_name=speaker.name,
            source_url=f"https://example.org/{year}/speakers/returning-builder",
            source_updated_at=now,
            resolution_status=HistoricalSourceIdentity.VERIFIED,
        )
        talk = HistoricalTalk.objects.create(
            edition=edition,
            external_key=f"talk-{year}",
            title=f"Reliable systems in {year}",
            source_url=f"https://example.org/{year}/talks/reliable-systems",
            source_updated_at=now,
        )
        HistoricalSpeakerCredit.objects.create(
            talk=talk,
            speaker=speaker,
            source_identity=identity,
            name_at_source=speaker.name,
            source_url=talk.source_url,
            source_updated_at=now,
        )
        talk.speakers.add(speaker)

    client.force_login(users["chair"])
    response = client.get(_org_url(event))

    assert response.status_code == 200
    assert response.context["program_memory"] == {
        "editions": 2,
        "talks": 2,
        "speaker_credits": 2,
        "source_identities": 2,
        "verified_returning_speakers": 1,
    }
    assert b"Program memory" in response.content
    assert b"release-locked provenance contract" in response.content
    assert b"Verified recurrence" in response.content
    memory_url = reverse(
        "plugins:speakerops:speakerops_conference_memory",
        kwargs={"event": event.slug},
    )
    assert memory_url.encode() in response.content


def test_crm_selected_contact_opens_addressable_controls_and_survives_actions(client, event, users):
    contact = CRMContact.objects.create(
        organiser=event.organiser,
        name="Casey Operator",
        email="casey@example.org",
        company="Continuity Labs",
        job_title="Program lead",
    )
    CRMPipelineCard.objects.create(organiser=event.organiser, contact=contact)
    client.force_login(users["chair"])
    url = _org_url(event)

    response = client.get(url, {"contact": contact.pk})

    assert response.status_code == 200
    assert response.context["selected_contact_id"] == contact.pk
    content = response.content.decode()
    document = BeautifulSoup(content, "html.parser")
    for element_id in (
        f"crm-contact-{contact.pk}",
        f"crm-edit-{contact.pk}",
        f"crm-connections-{contact.pk}",
        f"crm-history-{contact.pk}",
    ):
        details = document.find("details", id=element_id)
        assert details is not None
        assert details.has_attr("open")
    assert f'href="{url}?contact={contact.pk}#crm-contact-{contact.pk}"' in content

    response = client.post(
        url,
        {
            "action": "save_contact",
            "contact_id": contact.pk,
            "name": contact.name,
            "email": contact.email,
            "company": contact.company,
            "job_title": contact.job_title,
            "tags": "alumni, AI",
            "internal_notes": "Return for the systems track.",
        },
    )

    assert response.status_code == 302
    assert response.url == _selected_url(url, contact)
    contact.refresh_from_db()
    assert contact.tags == ["AI", "alumni"]
    assert contact.internal_notes == "Return for the systems track."

    response = client.post(
        url,
        {
            "action": "move_stage",
            "contact_id": contact.pk,
            "stage": CRMPipelineCard.INTERESTED,
            "note": "Asked to see the returning-speaker context.",
        },
    )

    assert response.status_code == 302
    assert response.url == _selected_url(url, contact)
