import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django_scopes import scope

from pretalx_speakerops.conference_memory import (
    conference_coverage,
    find_related_talks,
    import_document,
    memory_decision_support,
    resolve_source_identity,
    speaker_memory_summary,
    verify_imported_catalog,
)
from pretalx_speakerops.history_coverage import analyze_catalog, build_contract
from pretalx_speakerops.models import (
    ConferenceEdition,
    ConferenceSeries,
    CRMContact,
    CRMPipelineCard,
    HistoricalIdentityDecision,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalSpeakerCredit,
    HistoricalTalk,
    SpeakerMemoryProfile,
)


def memory_document(title="AI-Assisted Contributions and Maintainer Load"):
    return {
        "schema_version": 1,
        "series": [
            {
                "slug": "pycon-us",
                "name": "PyCon US",
                "website": "https://us.pycon.org/",
                "source_policy": {"license_review": "required-before-republication"},
                "editions": [
                    {
                        "external_key": "2026",
                        "name": "PyCon US 2026",
                        "date_from": "2026-05-13",
                        "date_to": "2026-05-19",
                        "location": "Long Beach, California",
                        "source_url": "https://us.pycon.org/2026/schedule/talks/",
                        "source_updated_at": "2026-08-09T12:00:00Z",
                        "talks": [
                            {
                                "external_key": "presentation-105",
                                "title": title,
                                "session_format": "Talk",
                                "track": "Artificial Intelligence",
                                "level": "Just starting out",
                                "topics": ["AI", "open source maintenance"],
                                "source_url": "https://us.pycon.org/2026/schedule/presentation/105/",
                                "speakers": [{"name": "Paolo Melchiorre"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def aie_memory_document(*, edition="2025", speaker="Returning Builder", title="Agent Evals"):
    document = memory_document(title)
    series = document["series"][0]
    series.update(
        slug="ai-engineer",
        name="AI Engineer",
        website="https://www.ai.engineer/",
        source_policy={
            "scope": "all discoverable official schedules",
            "known_gaps": [{"item": "unpublished-track", "reason": "Source has no label"}],
        },
    )
    edition_record = series["editions"][0]
    edition_record.update(
        external_key=edition,
        name=f"AI Engineer {edition}",
        date_from=f"{edition}-06-01",
        date_to=f"{edition}-06-03",
        source_url=f"https://www.ai.engineer/worldsfair/{edition}/schedule",
    )
    talk = edition_record["talks"][0]
    talk.update(
        external_key=f"agent-evals-{edition}",
        title=title,
        session_format="Stage Talk",
        track="Evals",
        topics=["Agents", "Evals"],
        source_url=f"https://www.ai.engineer/worldsfair/{edition}/schedule/agent-evals",
        speakers=[{"name": speaker}],
    )
    return document


@pytest.mark.django_db
def test_history_import_is_idempotent_and_updates_changed_records():
    first = import_document(memory_document())
    second = import_document(memory_document("Updated title"))

    assert first.series == first.editions == first.talks == first.speakers == 1
    assert first.source_identities == 1
    assert second.series == second.editions == second.talks == second.speakers == 0
    assert second.source_identities == 0
    assert ConferenceSeries.objects.count() == 1
    assert ConferenceEdition.objects.count() == 1
    assert HistoricalSpeaker.objects.get().name == "Paolo Melchiorre"
    assert HistoricalSpeakerCredit.objects.get().name_at_source == "Paolo Melchiorre"
    assert HistoricalSpeakerCredit.objects.get().source_identity.source_key == (
        "credit:presentation-105:0"
    )
    assert HistoricalTalk.objects.get().title == "Updated title"


@pytest.mark.django_db
def test_history_import_preserves_field_level_provenance():
    document = memory_document()
    document["series"][0]["editions"][0]["talks"][0]["field_provenance"] = {
        "track": {
            "source_url": "https://us.pycon.org/2026/schedule/talks/",
            "source_updated_at": "2026-08-09T12:00:00Z",
            "method": "exact title match against organizer schedule",
        }
    }

    import_document(document)

    evidence = HistoricalTalk.objects.get().field_provenance["track"]
    assert evidence["source_url"] == "https://us.pycon.org/2026/schedule/talks/"
    assert evidence["method"] == "exact title match against organizer schedule"
    assert evidence["source_updated_at"] == "2026-08-09T12:00:00+00:00"


@pytest.mark.django_db
def test_history_import_rejects_unverifiable_field_provenance():
    document = memory_document()
    document["series"][0]["editions"][0]["talks"][0]["field_provenance"] = {
        "track": {"source_url": "http://example.org/schedule"}
    }

    with pytest.raises(ValueError, match="must use HTTPS"):
        import_document(document)


@pytest.mark.django_db
def test_import_verification_fails_on_missing_credit(tmp_path):
    document = memory_document()
    source = tmp_path / "history.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    import_document(document)

    assert verify_imported_catalog(source).complete
    HistoricalSpeakerCredit.objects.all().delete()
    report = verify_imported_catalog(source)
    assert not report.complete
    assert report.speaker_credits == 0
    assert any(error.startswith("speaker credits differ") for error in report.errors)


@pytest.mark.django_db
def test_import_command_accepts_local_normalized_document(tmp_path):
    source = tmp_path / "history.json"
    source.write_text(json.dumps(memory_document()), encoding="utf-8")

    call_command("speakerops_import_history", source)

    assert HistoricalTalk.objects.filter(external_key="presentation-105").exists()


@pytest.mark.django_db
def test_import_command_verifies_exact_contracted_database(tmp_path):
    starter = json.loads(
        (
            Path(__file__).parents[1]
            / "pretalx_speakerops"
            / "data"
            / "conference_history_starter.json"
        ).read_text()
    )
    for series in starter["series"]:
        series["source_policy"] = {
            "scope": "all official records in this verification fixture",
            "known_gaps": [],
        }
        for edition in series["editions"]:
            for talk in edition["talks"]:
                talk.setdefault("source_updated_at", edition["source_updated_at"])
    source = tmp_path / "catalog"
    source.mkdir()
    (source / "history.json").write_text(json.dumps(starter), encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(build_contract(analyze_catalog(source))), encoding="utf-8")
    report_path = tmp_path / "verification.json"

    call_command(
        "speakerops_import_history",
        source,
        contract=contract,
        verify=True,
        report=report_path,
    )

    report = json.loads(report_path.read_text())
    assert report["catalog"]["structurally_complete"]
    assert report["database"]["complete"]
    assert report["database"]["talks"] == 6

    broken_contract = json.loads(contract.read_text())
    broken_contract["totals"]["talks"] += 1
    contract.write_text(json.dumps(broken_contract), encoding="utf-8")
    with pytest.raises(CommandError, match="does not match its contract"):
        call_command(
            "speakerops_import_history",
            source,
            contract=contract,
            verify=True,
        )


@pytest.mark.django_db
def test_import_rejects_duplicate_talk_keys_atomically():
    document = memory_document()
    talks = document["series"][0]["editions"][0]["talks"]
    talks.append(dict(talks[0]))

    with pytest.raises(ValueError, match="Duplicate talk key"):
        import_document(document)

    assert ConferenceSeries.objects.count() == 0


@pytest.mark.django_db
def test_import_rejects_reused_person_key_for_different_people_atomically():
    first = memory_document("First")
    first_speaker = first["series"][0]["editions"][0]["talks"][0]["speakers"][0]
    first_speaker.update(name="Sarah Adigwe", canonical_key="R8PQYJ")
    import_document(first)
    second = memory_document("Second")
    second["series"][0]["editions"][0].update(
        external_key="2027",
        name="PyLadiesCon 2027",
    )
    second_speaker = second["series"][0]["editions"][0]["talks"][0]["speakers"][0]
    second_speaker.update(name="Marie-Louise Annan", canonical_key="R8PQYJ")

    with pytest.raises(ValueError, match="cannot map both"):
        import_document(second)

    assert HistoricalSpeaker.objects.get(canonical_key="R8PQYJ").name == "Sarah Adigwe"
    assert ConferenceEdition.objects.filter(external_key="2027").count() == 0


@pytest.mark.django_db
def test_audited_identity_link_survives_reimport_and_drives_verified_recurrence():
    first = aie_memory_document(edition="2024", speaker="Sarah Adigwe")
    second = aie_memory_document(edition="2025", speaker="Sarah Adigwe")
    first["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = "sarah-2024"
    second["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = "sarah-2025"
    import_document(first)
    import_document(second)
    identities = list(HistoricalSourceIdentity.objects.order_by("edition__external_key"))

    resolve_source_identity(
        identities[1],
        identities[0].speaker,
        actor=None,
        action=HistoricalIdentityDecision.LINK,
        reason="Reviewed official speaker pages identify the same person.",
        evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
    )
    import_document(second)
    identities[1].refresh_from_db()

    assert identities[1].speaker == identities[0].speaker
    assert identities[1].resolution_status == HistoricalSourceIdentity.VERIFIED
    assert HistoricalIdentityDecision.objects.count() == 1
    insights = memory_decision_support(HistoricalTalk.objects.all())
    assert insights["returning_speakers"][0].name == "Sarah Adigwe"
    assert insights["returning_speakers"][0].edition_count == 2


@pytest.mark.django_db
def test_identity_link_rejects_duplicate_credit_on_same_talk_atomically():
    document = aie_memory_document(edition="2025", speaker="First Speaker")
    talk = document["series"][0]["editions"][0]["talks"][0]
    talk["speakers"].append(
        {
            "canonical_key": "second-speaker",
            "name": "Second Speaker",
        }
    )
    import_document(document)
    identities = list(HistoricalSourceIdentity.objects.order_by("source_key"))
    source_identity = identities[1]
    target_speaker = identities[0].speaker

    with pytest.raises(ValueError, match="duplicate speaker credit"):
        resolve_source_identity(
            source_identity,
            target_speaker,
            actor=None,
            action=HistoricalIdentityDecision.LINK,
            reason="The official schedule was reviewed.",
            evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
        )

    source_identity.refresh_from_db()
    assert source_identity.speaker != target_speaker
    assert HistoricalIdentityDecision.objects.count() == 0
    assert (
        HistoricalSpeakerCredit.objects.filter(talk__external_key="agent-evals-2025").count() == 2
    )


@pytest.mark.django_db
def test_import_verification_allows_audited_operator_split(tmp_path):
    document = aie_memory_document(edition="2025", speaker="Published Alias")
    source = tmp_path / "history.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    import_document(document)
    identity = HistoricalSourceIdentity.objects.get()
    resolved_speaker = HistoricalSpeaker.objects.create(
        canonical_key="operator-reviewed-person",
        name="Published Alias",
        biography="",
        source_url=identity.source_url,
        source_updated_at=identity.source_updated_at,
    )

    resolve_source_identity(
        identity,
        resolved_speaker,
        actor=None,
        action=HistoricalIdentityDecision.SPLIT,
        reason="The official profile establishes a distinct person.",
        evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
    )

    report = verify_imported_catalog(source)
    assert report.complete
    assert report.speakers == 2


@pytest.mark.django_db(transaction=True)
def test_identity_review_ui_requires_evidence_and_records_actor(event, users, client):
    first = aie_memory_document(edition="2024", speaker="Sarah Adigwe")
    second = aie_memory_document(edition="2025", speaker="Sarah Adigwe")
    first["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = "sarah-2024"
    second["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = "sarah-2025"
    import_document(first)
    import_document(second)
    identities = list(HistoricalSourceIdentity.objects.order_by("edition__external_key"))
    source = identities[1]
    target = identities[0]
    url = reverse(
        "plugins:speakerops:speakerops_conference_speaker",
        kwargs={"event": event.slug, "pk": source.speaker_id},
    )
    client.force_login(users["chair"])

    rejected = client.post(
        url,
        {
            "action": "resolve_identity",
            "source_identity": source.pk,
            "identity_action": HistoricalIdentityDecision.LINK,
            "target_key": target.speaker.canonical_key,
            "reason": "Same person on reviewed schedules",
            "evidence_url": "",
        },
    )
    assert rejected.status_code == 302
    assert HistoricalIdentityDecision.objects.count() == 0

    accepted = client.post(
        url,
        {
            "action": "resolve_identity",
            "source_identity": source.pk,
            "identity_action": HistoricalIdentityDecision.LINK,
            "target_key": target.speaker.canonical_key,
            "reason": "Same person on reviewed official schedules",
            "evidence_url": "https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
        },
    )
    source.refresh_from_db()
    decision = HistoricalIdentityDecision.objects.get()

    assert accepted.status_code == 302
    assert source.speaker == target.speaker
    assert decision.actor == users["chair"]
    assert decision.reason == "Same person on reviewed official schedules"


@pytest.mark.django_db(transaction=True)
def test_cfp_guide_is_public_and_linked_from_cfp(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])

    guide_url = reverse("plugins:speakerops:speakerops_cfp_guide", kwargs={"event": event.slug})
    guide = client.get(guide_url)
    cfp = client.get(reverse("cfp:event.start", kwargs={"event": event.slug}))

    assert guide.status_code == 200
    assert b"Write a proposal reviewers can champion" in guide.content
    assert b"https://www.youtube.com/watch?v=qpmZID27t98" in guide.content
    assert b"https://www.youtube.com/watch?v=5nOLb27hQ5w" in guide.content
    assert cfp.status_code == 200
    assert guide_url.encode() in cfp.content


@pytest.mark.django_db(transaction=True)
def test_chair_and_reviewer_can_query_conference_memory(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
    import_document(memory_document())
    url = reverse("plugins:speakerops:speakerops_conference_memory", kwargs={"event": event.slug})

    client.force_login(users["chair"])
    matching = client.get(url, {"q": "maintainer"})
    assert matching.status_code == 200
    assert b"AI-Assisted Contributions" in matching.content
    assert b"Paolo Melchiorre" in matching.content

    client.force_login(users["reviewer"])
    reviewer_response = client.get(url, {"q": "maintainer"})
    assert reviewer_response.status_code == 200
    assert b"AI-Assisted Contributions" in reviewer_response.content


@pytest.mark.django_db(transaction=True)
def test_speaker_crm_layers_tags_notes_and_review_history_without_mutating_source(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        proposal = event.submissions.first()
        proposal.speakers.add(users["speaker"])
        users["speaker"].name = "Paolo Melchiorre"
        users["speaker"].save(update_fields=["name"])
    import_document(memory_document())
    speaker = HistoricalSpeaker.objects.get(name="Paolo Melchiorre")
    source_biography = speaker.biography
    url = reverse(
        "plugins:speakerops:speakerops_conference_speaker",
        kwargs={"event": event.slug, "pk": speaker.pk},
    )

    client.force_login(users["chair"])
    saved = client.post(
        url,
        {
            "tags": "AIE alum, Evals, AIE alum",
            "internal_notes": "Invite again after the evaluation systems track matures.",
        },
    )
    assert saved.status_code == 302
    with scope(event=event):
        profile = SpeakerMemoryProfile.objects.get(event=event, speaker=speaker)
    assert profile.tags == ["AIE alum", "Evals"]
    assert profile.updated_by == users["chair"]
    page = client.get(url)
    assert page.status_code == 200
    assert b"Cross-event talk history" in page.content
    assert b"Decision brief" in page.content
    assert b"Cross-event identity cluster" in page.content
    assert b"Provisional recurrence candidate" in page.content
    assert b"Published expertise signals" in page.content
    assert b"Current-program review history" in page.content
    assert b"Invite again" in page.content
    assert b"Add to organization CRM" in page.content

    handoff = client.post(url, {"action": "add_to_crm"})
    contact = CRMContact.objects.get(organiser=event.organiser, source_speaker=speaker)
    assert handoff.status_code == 302
    assert handoff.url.endswith(f"#crm-contact-{contact.pk}")
    assert contact.name == speaker.name
    assert contact.biography == speaker.biography
    assert contact.tags == ["AIE alum", "Evals"]
    assert "Invite again" in contact.internal_notes
    assert CRMPipelineCard.objects.filter(contact=contact, organiser=event.organiser).exists()
    client.post(url, {"action": "add_to_crm"})
    assert CRMContact.objects.filter(organiser=event.organiser, source_speaker=speaker).count() == 1

    speaker.refresh_from_db()
    assert speaker.biography == source_biography

    client.force_login(users["reviewer"])
    reviewer_page = client.get(url)
    assert reviewer_page.status_code == 200
    assert b"Internal notes" not in reviewer_page.content
    assert client.post(url, {"internal_notes": "must not save"}).status_code == 404


@pytest.mark.django_db
def test_verified_starter_catalog_covers_all_six_conference_families():
    source = (
        Path(__file__).parents[1]
        / "pretalx_speakerops"
        / "data"
        / "conference_history_starter.json"
    )
    call_command("speakerops_import_history", source)

    assert set(ConferenceSeries.objects.values_list("slug", flat=True)) == {
        "ai-engineer",
        "pycon-us",
        "jsconf",
        "gdc",
        "goto",
        "strange-loop",
    }
    assert HistoricalTalk.objects.count() == 6
    assert all(
        talk.title
        and talk.session_format
        and talk.track
        and talk.source_url
        and talk.source_updated_at
        and talk.speakers.exists()
        for talk in HistoricalTalk.objects.all()
    )


@pytest.mark.django_db
def test_import_command_loads_catalog_directory_atomically(tmp_path):
    first = memory_document()
    second = memory_document("Second source file updates the same talk")
    (tmp_path / "01.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "02.json").write_text(json.dumps(second), encoding="utf-8")

    call_command("speakerops_import_history", tmp_path)

    assert HistoricalTalk.objects.get().title == "Second source file updates the same talk"


@pytest.mark.django_db
def test_import_marks_source_omissions_without_inventing_metadata():
    document = memory_document()
    talk = document["series"][0]["editions"][0]["talks"][0]
    talk["session_format"] = ""
    talk["track"] = ""

    import_document(document)

    imported = HistoricalTalk.objects.get()
    assert imported.session_format == "Not provided by source"
    assert imported.track == "Not provided by source"


@pytest.mark.django_db
def test_refresh_preserves_missing_records_unless_prune_is_explicit():
    document = memory_document()
    import_document(document)
    document["series"][0]["editions"][0]["talks"] = []

    preserved = import_document(document)
    assert preserved.deleted_talks == 0
    assert HistoricalTalk.objects.count() == 1

    pruned = import_document(document, prune=True)
    assert pruned.deleted_talks == 1
    assert HistoricalTalk.objects.count() == 0
    identity = HistoricalSourceIdentity.objects.get()
    assert identity.active is False
    assert identity.retired_at is not None
    assert HistoricalSpeaker.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_related_history_surfaces_title_and_returning_speaker_evidence(event, users):
    import_document(memory_document())
    with scope(event=event):
        proposal = event.submissions.first()
        proposal.title = "AI-assisted maintainer contributions"
        proposal.save(update_fields=["title", "updated"])
        proposal.speakers.add(users["speaker"])
        users["speaker"].name = "Paolo Melchiorre"
        users["speaker"].save(update_fields=["name"])

        matches = find_related_talks(proposal)

    assert [talk.external_key for talk in matches] == ["presentation-105"]
    assert matches[0].speakerops_match_reason == "returning speaker"


@pytest.mark.django_db(transaction=True)
def test_conference_memory_paginates_large_result_sets(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
    for index in range(51):
        document = memory_document(f"Repeated memory talk {index:02d}")
        document["series"][0]["editions"][0]["talks"][0]["external_key"] = f"talk-{index}"
        import_document(document)

    client.force_login(users["reviewer"])
    url = reverse("plugins:speakerops:speakerops_conference_memory", kwargs={"event": event.slug})
    first = client.get(url, {"q": "Repeated memory"})
    second = client.get(url, {"q": "Repeated memory", "page": 2})

    assert first.status_code == second.status_code == 200
    assert first.context["result_count"] == 51
    assert first.context["page_obj"].number == 1
    assert first.context["page_obj"].paginator.num_pages == 2
    assert second.context["page_obj"].number == 2


@pytest.mark.django_db
def test_memory_decision_support_compares_aie_peers_and_return_cadence():
    import_document(aie_memory_document(edition="2024"))
    import_document(aie_memory_document(edition="2025"))
    import_document(memory_document("Peer Agent Evals"))
    source_identities = list(
        HistoricalSourceIdentity.objects.filter(edition__series__slug="ai-engineer").order_by(
            "edition__external_key"
        )
    )
    assert all(
        identity.resolution_status == HistoricalSourceIdentity.LEGACY_UNVERIFIED
        for identity in source_identities
    )
    decision = resolve_source_identity(
        source_identities[1],
        source_identities[0].speaker,
        actor=None,
        action=HistoricalIdentityDecision.LINK,
        reason="Official schedules use the same published speaker identity.",
        evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
    )

    insights = memory_decision_support(HistoricalTalk.objects.all())

    assert decision.prior_speaker == decision.resolved_speaker
    assert HistoricalIdentityDecision.objects.count() == 1
    assert insights["aie"]["talks"] == 2
    assert insights["aie"]["editions"] == 2
    assert insights["peers"]["talks"] == 1
    assert insights["returning_speakers"][0].name == "Returning Builder"
    assert insights["returning_speakers"][0].edition_count == 2
    assert {row["label"]: row for row in insights["formats"]}["Stage Talk"] == {
        "label": "Stage Talk",
        "aie": 2,
        "peers": 0,
    }
    assert {row["label"]: row for row in insights["topics"]}["Evals"]["aie"] == 2


@pytest.mark.django_db
def test_speaker_memory_summary_exposes_recurrence_aliases_and_metadata_gaps():
    first = aie_memory_document(edition="2024", speaker="Returning Builder")
    second = aie_memory_document(edition="2025", speaker="R. Builder")
    first["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = (
        "returning-builder-2024"
    )
    second["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = (
        "returning-builder-2025"
    )
    second["series"][0]["editions"][0]["talks"][0]["track"] = ""
    import_document(first)
    import_document(second)
    identities = list(HistoricalSourceIdentity.objects.order_by("edition__external_key"))
    resolve_source_identity(
        identities[1],
        identities[0].speaker,
        actor=None,
        action=HistoricalIdentityDecision.LINK,
        reason="Reviewed aliases on the two official schedule pages.",
        evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
    )
    speaker = identities[0].speaker
    talks = list(
        speaker.historical_talks.select_related("edition__series").prefetch_related(
            "credits__speaker"
        )
    )

    summary = speaker_memory_summary(speaker, talks)

    assert summary["talk_count"] == 2
    assert summary["edition_count"] == 2
    assert summary["series_count"] == 1
    assert summary["aliases"] == ["R. Builder", "Returning Builder"]
    assert summary["metadata_coverage"] == 83
    assert summary["missing_track"] == 1
    assert summary["topics"][0] == {"label": "Agents", "count": 2}


@pytest.mark.django_db(transaction=True)
def test_speaker_page_links_current_reviews_through_sourced_aliases(event, users, client):
    first = aie_memory_document(edition="2024", speaker="Returning Builder")
    second = aie_memory_document(edition="2025", speaker="R. Builder")
    first["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = (
        "returning-builder-2024"
    )
    second["series"][0]["editions"][0]["talks"][0]["speakers"][0]["canonical_key"] = (
        "returning-builder-2025"
    )
    import_document(first)
    import_document(second)
    identities = list(HistoricalSourceIdentity.objects.order_by("edition__external_key"))
    resolve_source_identity(
        identities[1],
        identities[0].speaker,
        actor=None,
        action=HistoricalIdentityDecision.LINK,
        reason="Reviewed aliases on the two official schedule pages.",
        evidence_url="https://www.ai.engineer/worldsfair/2025/schedule/agent-evals",
    )
    with scope(event=event):
        proposal = event.submissions.filter(reviews__isnull=False).first()
        users["speaker"].name = "Returning Builder"
        users["speaker"].save(update_fields=["name"])
        proposal.speakers.add(users["speaker"])
    speaker = identities[0].speaker

    client.force_login(users["chair"])
    response = client.get(
        reverse(
            "plugins:speakerops:speakerops_conference_speaker",
            kwargs={"event": event.slug, "pk": speaker.pk},
        )
    )

    assert response.status_code == 200
    assert response.context["memory_summary"]["talk_count"] == 2
    assert response.context["identity_summary"]["verified_recurrence"] is True
    assert b"Verified recurrence" in response.content
    assert b"sourced talks" in response.content
    assert b"Returning Builder" in response.content
    assert b"R. Builder" in response.content
    assert proposal.title.encode() in response.content


@pytest.mark.django_db
def test_coverage_exposes_gaps_freshness_and_label_confidence_without_inference():
    document = aie_memory_document()
    talk = document["series"][0]["editions"][0]["talks"][0]
    talk["track"] = ""
    import_document(document)

    coverage = conference_coverage()

    assert len(coverage) == 1
    series = coverage[0]
    assert series.speakerops_declared_gaps == 1
    assert series.speakerops_missing_track == 1
    assert series.speakerops_missing_format == 0
    assert series.speakerops_label_coverage == 50
    assert series.speakerops_last_checked.isoformat() == "2026-08-09T12:00:00+00:00"
    assert series.speakerops_editions[0].speakerops_label_coverage == 50


@pytest.mark.django_db(transaction=True)
def test_memory_page_labels_decision_support_and_provenance_limits(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
    import_document(aie_memory_document())
    client.force_login(users["reviewer"])

    response = client.get(
        reverse("plugins:speakerops:speakerops_conference_memory", kwargs={"event": event.slug}),
        {"q": "Agent"},
    )

    assert response.status_code == 200
    assert b"AIE decision support" in response.content
    assert b"They do not rank a proposal" in response.content
    assert b"What \xe2\x80\x9cfull known backfill\xe2\x80\x9d means" in response.content
    assert b"declared source gaps" in response.content
    assert b"Source has no label" in response.content
    assert b"No explicitly verified identity currently spans" in response.content
