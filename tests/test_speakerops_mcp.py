import asyncio
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django_scopes import scope
from mcp.types import CallToolRequestParams, RequestParams

from pretalx_speakerops.buzz_reads import (
    conference_memory,
    conference_memory_message,
    content_readiness,
    content_readiness_message,
    release_readiness,
    release_readiness_message,
    render_content_readiness,
    render_release_readiness,
)
from pretalx_speakerops.conference_memory import SOURCE_NOT_PROVIDED
from pretalx_speakerops.models import (
    ConferenceEdition,
    ConferenceSeries,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalSpeakerCredit,
    HistoricalTalk,
    OnboardingTask,
    SessionPublicationApproval,
    TaskEvidence,
)
from pretalx_speakerops.onboarding.services import ensure_acceptance_plan, record_evidence
from tools import mcp_speakerops_server as bridge

ALL_BUZZ_READS = (
    "release_readiness,speaker_nudges,review_progress,content_readiness,"
    "sync_recovery,speaker_next_actions,reviewer_next_assignment,"
    "executive_readiness,conference_memory"
)


def _arrange_room_conflict(event, users):
    with scope(event=event):
        talks = list(
            event.wip_schedule.talks.filter(submission__isnull=False)
            .select_related("submission", "room")
            .order_by("pk")
        )
        first, second = talks[:2]
        room = event.rooms.first()
        start = timezone.now().replace(microsecond=0)
        first.submission.speakers.set([users["chair"]])
        second.submission.speakers.set([users["reviewer"]])
        for talk in (first, second):
            talk.room = room
            talk.start = start
            talk.end = start + timedelta(minutes=30)
            talk.save(update_fields=["room", "start", "end", "updated"])
        return first, second


_UPLOAD_FILES = (
    ("headshot", "headshot.jpg", b"\xff\xd8\xff" + b"demo", "image/jpeg"),
    ("slides", "deck.pdf", b"%PDF-1.7\ndemo\n%%EOF", "application/pdf"),
    ("supporting-document", "handout.pdf", b"%PDF-1.7\nhandout\n%%EOF", "application/pdf"),
)


def _scope_bridge(
    monkeypatch,
    *event_slugs,
    base_url="https://example.test",
    subject_email="",
):
    monkeypatch.setenv("SPEAKEROPS_MCP_PRINCIPAL", "test-read-principal")
    monkeypatch.setenv("SPEAKEROPS_MCP_ALLOWED_EVENTS", ",".join(event_slugs))
    monkeypatch.setenv(
        "SPEAKEROPS_MCP_CAPABILITIES",
        ALL_BUZZ_READS,
    )
    monkeypatch.setenv("SPEAKEROPS_BASE_URL", base_url)
    if subject_email:
        monkeypatch.setenv("SPEAKEROPS_MCP_SUBJECT_EMAIL", subject_email)
    else:
        monkeypatch.delenv("SPEAKEROPS_MCP_SUBJECT_EMAIL", raising=False)


def test_django_startup_diagnostics_do_not_pollute_jsonrpc_stdout(capsys):
    def noisy_setup():
        print("pretalx startup diagnostic")

    bridge._setup_django(noisy_setup)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pretalx startup diagnostic\n"


def _arrange_verified_conference_memory():
    updated = timezone.now()
    series = ConferenceSeries.objects.create(
        slug="ai-engineer",
        name="AI Engineer",
        website="https://www.ai.engineer/",
        source_policy={"known_gaps": ["Some source tracks are not published."]},
    )
    speaker = HistoricalSpeaker.objects.create(
        canonical_key="returning-builder",
        name="Returning Builder",
        source_url="https://www.ai.engineer/speakers/returning-builder",
        source_updated_at=updated,
    )
    for year in (2024, 2025):
        edition = ConferenceEdition.objects.create(
            series=series,
            external_key=str(year),
            name=f"AI Engineer {year}",
            date_from=date(year, 6, 1),
            date_to=date(year, 6, 3),
            source_url=f"https://www.ai.engineer/worldsfair/{year}/schedule",
            source_updated_at=updated,
        )
        identity = HistoricalSourceIdentity.objects.create(
            edition=edition,
            source_key=f"returning-builder-{year}",
            speaker=speaker,
            display_name="Returning Builder",
            source_url=f"https://www.ai.engineer/worldsfair/{year}/speakers/returning-builder",
            source_updated_at=updated,
            resolution_status=HistoricalSourceIdentity.VERIFIED,
        )
        talk = HistoricalTalk.objects.create(
            edition=edition,
            external_key=f"agent-evals-{year}",
            title=f"Agent Evals in {year}",
            abstract="A sourced evaluation practice.",
            session_format="Talk",
            track="" if year == 2024 else "Evaluation",
            topics=["Agents", "Evals"],
            source_url=f"https://www.ai.engineer/worldsfair/{year}/schedule/agent-evals",
            source_updated_at=updated,
        )
        talk.speakers.add(speaker)
        HistoricalSpeakerCredit.objects.create(
            talk=talk,
            speaker=speaker,
            source_identity=identity,
            name_at_source="Returning Builder",
            source_url=identity.source_url,
            source_updated_at=updated,
        )
    return speaker


def _make_session_content(
    event, users, submission, speaker, slides_action="approve", slides_note=""
):
    """Give a session upload evidence for every upload file request.

    Everything is approved except slides, which takes ``slides_action``
    (``approve`` or ``request-changes``). Returns ``{slug: evidence}``.
    """
    # submission_state_change is an EventPluginSignal: the acceptance receiver
    # that provisions onboarding tasks only fires when the plugin is enabled
    # for the event.
    if "pretalx_speakerops" not in event.plugin_list:
        event.enable_plugin("pretalx_speakerops")
        event.save()
    submission.speakers.set([speaker])
    submission.accept(person=users["chair"], force=True)
    ensure_acceptance_plan(submission)
    results = {}
    for slug, filename, data, content_type in _UPLOAD_FILES:
        task = OnboardingTask.objects.get(
            event=event, submission=submission, speaker=speaker, definition__slug=slug
        )
        evidence, _ = record_evidence(
            task,
            speaker,
            "upload",
            upload=SimpleUploadedFile(filename, data, content_type=content_type),
        )
        if slug != "slides":
            evidence.review_status = TaskEvidence.APPROVED
            evidence.reviewed_by = users["chair"]
            evidence.reviewed_at = timezone.now()
        else:
            evidence.review_status = (
                TaskEvidence.APPROVED
                if slides_action == "approve"
                else TaskEvidence.CHANGES_REQUESTED
            )
            evidence.review_note = slides_note
            evidence.reviewed_by = users["chair"]
            evidence.reviewed_at = timezone.now()
        evidence.save(
            update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at", "updated"]
        )
        results[slug] = evidence
    return results


def _session_ready(event, users, submission, speaker):
    results = _make_session_content(event, users, submission, speaker, slides_action="approve")
    return results["slides"]


def _session_changes_requested(event, users, submission, speaker, note="Add the licensing slide."):
    results = _make_session_content(
        event, users, submission, speaker, slides_action="request-changes", slides_note=note
    )
    return results["slides"]


@pytest.mark.django_db(transaction=True)
def test_release_readiness_reports_conflicts_and_links(event, users):
    first, second = _arrange_room_conflict(event, users)
    result = release_readiness(event.slug, base_url="http://example.test")

    assert result["event"] == event.slug
    assert result["release_blocked"] is True
    assert result["blocking_reasons"] == ["schedule_conflicts"]
    assert result["schedule"]["has_wip"] is True
    assert result["attention"] == {
        "overdue_tasks": 0,
        "undecided_proposals": 0,
        "unapproved_content": 0,
        "sync_errors": 0,
    }

    conflicts = result["conflicts"]
    assert any(
        row["type"] == "room"
        and row["blocking"] is True
        and row["resource"] == f"room {first.room.name}"
        and row["talk"]["pk"] == first.pk
        for row in conflicts
    )
    conflict = next(
        row
        for row in conflicts
        if row["type"] == "room"
        and row["talk"]["pk"] in {first.pk, second.pk}
        and row["competitor"]["pk"] in {first.pk, second.pk}
    )
    assert conflict["competitor"]["pk"] in {first.pk, second.pk}
    assert conflict["links"] == {
        "conflict": (
            f"http://example.test/go/agenda-release/{event.slug}/"
            f"#conflict-{conflict['conflict_key']}"
        ),
        "talk_slot": (
            f"http://example.test/go/agenda-release/{event.slug}/#slot-{conflict['talk']['pk']}"
        ),
        "competitor_slot": (
            f"http://example.test/go/agenda-release/{event.slug}/"
            f"#slot-{conflict['competitor']['pk']}"
        ),
    }

    links = result["links"]
    assert links["conflicts"] == (
        f"http://example.test/go/conflicts-drilldown/{event.slug}~conflicts/"
    )
    assert links["agenda"] == f"http://example.test/go/agenda-release/{event.slug}/"
    assert links["content"] == f"http://example.test/go/content-console/{event.slug}/"
    assert links["decisions"] == f"http://example.test/go/program-decisions/{event.slug}/"
    assert links["operations"] == f"http://example.test/go/operations-dashboard/{event.slug}/"

    assert "generated_at" in result
    assert result["generated_at"].endswith("+00:00") or result["generated_at"].endswith("Z")


@pytest.mark.django_db(transaction=True)
def test_release_readiness_default_base_url(event):
    result = release_readiness(event.slug)
    assert result["links"]["operations"].startswith("http://localhost:8000/go/")


@pytest.mark.django_db(transaction=True)
def test_release_readiness_clean_event_not_blocked(event):
    with scope(event=event):
        start = timezone.now().replace(microsecond=0)
        for offset, talk in enumerate(
            event.wip_schedule.talks.filter(submission__isnull=False).order_by("pk")
        ):
            talk.start = start + timedelta(days=offset)
            talk.end = talk.start + timedelta(minutes=30)
            talk.save(update_fields=["start", "end", "updated"])
    result = release_readiness(event.slug)
    assert result["event"] == event.slug
    assert result["release_blocked"] is False
    assert result["conflicts"] == []
    assert result["blocking_reasons"] == []


@pytest.mark.django_db(transaction=True)
def test_release_readiness_blocks_unapproved_content_without_schedule_conflicts(event):
    with scope(event=event):
        start = timezone.now().replace(microsecond=0)
        for offset, talk in enumerate(
            event.wip_schedule.talks.filter(submission__isnull=False).order_by("pk")
        ):
            talk.start = start + timedelta(days=offset)
            talk.end = talk.start + timedelta(minutes=30)
            talk.save(update_fields=["start", "end", "updated"])
        submission = event.submissions.first()
        SessionPublicationApproval.objects.create(
            event=event,
            submission=submission,
            status=SessionPublicationApproval.PENDING,
        )

    result = release_readiness(event.slug)

    assert result["conflicts"] == []
    assert result["attention"]["unapproved_content"] == 1
    assert result["release_blocked"] is True
    assert result["blocking_reasons"] == ["unapproved_content"]


@pytest.mark.django_db
def test_release_readiness_unknown_event_raises():
    with pytest.raises(KeyError):
        release_readiness("no-such-event")


@pytest.mark.django_db(transaction=True)
def test_release_readiness_message_formats_verdict_sources_and_trace(event, users):
    first, second = _arrange_room_conflict(event, users)
    message = release_readiness_message(event.slug, base_url="http://example.test")

    assert message.startswith(f"# Release readiness — {event.slug}")
    assert "**Blocked**" in message
    assert "schedule conflicts" in message

    assert "## Sources — canonical URL list" in message
    assert "pretalx_speakerops/canonical_links.py" in message
    assert f"http://example.test/go/conflicts-drilldown/{event.slug}~conflicts/" in message
    assert "| conflicts-drilldown |" in message
    assert "| speakerops_drilldown | organiser | filtered-collection |" in message
    assert "| operations-dashboard |" in message

    assert "## Trace of inference" in message
    lines = message.splitlines()
    assert any(line.startswith("1. Resolved event") for line in lines)
    assert any(line.startswith("2. Read WIP schedule") for line in lines)
    assert any(line.startswith("3. Classified schedule warnings") for line in lines)
    assert any(line.startswith("7. Verdict: release_blocked = true") for line in lines)
    assert any("Built 5 go/ links" in line for line in lines)

    assert any("Generated " in line and "(ISO-8601)" in line for line in lines)
    assert "http://example.test" in message


@pytest.mark.django_db(transaction=True)
def test_release_readiness_message_clean_event_not_blocked(event):
    with scope(event=event):
        start = timezone.now().replace(microsecond=0)
        for offset, talk in enumerate(
            event.wip_schedule.talks.filter(submission__isnull=False).order_by("pk")
        ):
            talk.start = start + timedelta(days=offset)
            talk.end = talk.start + timedelta(minutes=30)
            talk.save(update_fields=["start", "end", "updated"])
    message = release_readiness_message(event.slug)

    assert "**Release-ready**" in message
    assert "no release-blocking schedule warnings" in message
    assert "Verdict: release_blocked = false" in message
    assert "## What blocks release" not in message


def test_render_release_readiness_requires_no_db():
    message = render_release_readiness(
        {
            "event": "demo",
            "release_blocked": True,
            "blocking_reasons": ["unapproved_content"],
            "conflicts": [],
            "attention": {
                "overdue_tasks": 0,
                "undecided_proposals": 0,
                "unapproved_content": 0,
                "sync_errors": 0,
            },
            "schedule": {"has_wip": True, "published_version": "2026-08-10"},
            "links": {
                "conflicts": "http://x/go/conflicts-drilldown/demo~conflicts/",
                "agenda": "http://x/go/agenda-release/demo/",
                "content": "http://x/go/content-console/demo/",
                "decisions": "http://x/go/program-decisions/demo/",
                "operations": "http://x/go/operations-dashboard/demo/",
            },
            "generated_at": "2026-08-11T00:00:00+00:00",
        }
    )
    assert "## Sources — canonical URL list" in message


def test_build_server_registers_tools():
    server = bridge.build_server()
    assert server.get_request_handler("tools/list") is not None
    assert server.get_request_handler("tools/call") is not None


def test_list_tools_exposes_release_readiness_schema(monkeypatch):
    _scope_bridge(monkeypatch, "speakerops-demo")
    result = asyncio.run(bridge._handle_list_tools(None, RequestParams()))
    assert len(result.tools) == 9
    assert {tool.name for tool in result.tools} == set(ALL_BUZZ_READS.split(","))
    tool = next(t for t in result.tools if t.name == "release_readiness")
    assert tool.input_schema["required"] == ["event_slug"]
    assert "event_slug" in tool.input_schema["properties"]
    assert "e.g." not in tool.input_schema["properties"]["event_slug"]["description"]
    assert tool.input_schema["properties"]["event_slug"]["enum"] == ["speakerops-demo"]
    assert "base_url" not in tool.input_schema["properties"]
    content = next(t for t in result.tools if t.name == "content_readiness")
    assert content.input_schema["required"] == ["event_slug"]
    assert "event_slug" in content.input_schema["properties"]
    memory = next(t for t in result.tools if t.name == "conference_memory")
    assert memory.input_schema["required"] == ["event_slug"]
    assert memory.input_schema["properties"]["query"]["maxLength"] == 160


def test_list_tools_exposes_only_principal_capabilities(monkeypatch):
    _scope_bridge(monkeypatch, "speakerops-demo")
    monkeypatch.setenv(
        "SPEAKEROPS_MCP_CAPABILITIES",
        "release_readiness,conference_memory",
    )

    result = asyncio.run(bridge._handle_list_tools(None, RequestParams()))

    assert [tool.name for tool in result.tools] == [
        "release_readiness",
        "conference_memory",
    ]


@pytest.mark.django_db(transaction=True)
def test_call_tool_returns_release_readiness_message(event, monkeypatch):
    _scope_bridge(monkeypatch, event.slug)
    params = CallToolRequestParams(
        name="release_readiness",
        arguments={"event_slug": event.slug},
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is not True
    text = result.content[0].text
    assert text.startswith(f"# Release readiness — {event.slug}")
    assert "## Sources — canonical URL list" in text
    assert "## Trace of inference" in text
    assert f"https://example.test/go/operations-dashboard/{event.slug}/" in text
    assert "Generated " in text


@pytest.mark.django_db(transaction=True)
def test_call_tool_unknown_event_is_error(monkeypatch):
    _scope_bridge(monkeypatch, "missing-event")
    params = CallToolRequestParams(
        name="release_readiness", arguments={"event_slug": "missing-event"}
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert "missing-event" in result.content[0].text


@pytest.mark.django_db(transaction=True)
def test_call_tool_rejects_event_outside_principal_scope(event, monkeypatch):
    _scope_bridge(monkeypatch, "different-event")
    params = CallToolRequestParams(name="release_readiness", arguments={"event_slug": event.slug})

    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert result.content[0].text == "event is not authorized for this read principal"


@pytest.mark.parametrize(
    "environ",
    (
        {},
        {
            "SPEAKEROPS_MCP_PRINCIPAL": "agent",
            "SPEAKEROPS_MCP_ALLOWED_EVENTS": "*",
            "SPEAKEROPS_MCP_CAPABILITIES": "release_readiness",
            "SPEAKEROPS_BASE_URL": "https://loop.dharmicdata.org",
        },
        {
            "SPEAKEROPS_MCP_PRINCIPAL": "agent",
            "SPEAKEROPS_MCP_ALLOWED_EVENTS": "speakerops-demo",
            "SPEAKEROPS_MCP_CAPABILITIES": "release_readiness",
            "SPEAKEROPS_BASE_URL": "http://public.example",
        },
    ),
)
def test_read_policy_fails_closed(environ):
    with pytest.raises(ValueError):
        bridge.load_read_policy(environ)


def test_read_policy_pins_principal_events_and_origin():
    policy = bridge.load_read_policy(
        {
            "SPEAKEROPS_MCP_PRINCIPAL": "buzz-demo-reader",
            "SPEAKEROPS_MCP_ALLOWED_EVENTS": "speakerops-demo,second-event",
            "SPEAKEROPS_MCP_CAPABILITIES": "release_readiness,conference_memory",
            "SPEAKEROPS_BASE_URL": "https://loop.dharmicdata.org/",
            "SPEAKEROPS_MCP_SUBJECT_EMAIL": "Speaker@Example.ORG",
        }
    )

    assert policy.principal == "buzz-demo-reader"
    assert policy.allowed_events == {"speakerops-demo", "second-event"}
    assert policy.capabilities == {"release_readiness", "conference_memory"}
    assert policy.base_url == "https://loop.dharmicdata.org"
    assert policy.subject_email == "speaker@example.org"


@pytest.mark.django_db(transaction=True)
def test_call_tool_rejects_capability_outside_principal_scope(event, monkeypatch):
    _scope_bridge(monkeypatch, event.slug)
    monkeypatch.setenv("SPEAKEROPS_MCP_CAPABILITIES", "content_readiness")
    params = CallToolRequestParams(name="release_readiness", arguments={"event_slug": event.slug})

    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert result.content[0].text == "tool is not authorized for this read principal"


@pytest.mark.django_db(transaction=True)
def test_self_scoped_tool_requires_and_injects_deployment_subject(event, monkeypatch):
    _scope_bridge(monkeypatch, event.slug)
    params = CallToolRequestParams(
        name="speaker_next_actions",
        arguments={"event_slug": event.slug},
    )
    denied = asyncio.run(bridge._handle_call_tool(None, params))
    assert denied.is_error is True
    assert denied.content[0].text == (
        "self-scoped tool requires a deployment-bound subject identity"
    )

    captured = {}

    def fake_read(event_slug, *, subject_email, base_url):
        captured.update(
            event_slug=event_slug,
            subject_email=subject_email,
            base_url=base_url,
        )
        return "subject-bound answer"

    monkeypatch.setitem(bridge.READS, "speaker_next_actions", fake_read)
    _scope_bridge(monkeypatch, event.slug, subject_email="Speaker@Example.ORG")
    allowed = asyncio.run(bridge._handle_call_tool(None, params))

    assert allowed.is_error is not True
    assert allowed.content[0].text == "subject-bound answer"
    assert captured == {
        "event_slug": event.slug,
        "subject_email": "speaker@example.org",
        "base_url": "https://example.test",
    }


def test_call_tool_unknown_tool_raises():
    params = CallToolRequestParams(name="bogus_tool", arguments={})
    with pytest.raises(ValueError):
        asyncio.run(bridge._handle_call_tool(None, params))


def test_call_tool_in_process_protocol_roundtrip(monkeypatch):
    _scope_bridge(monkeypatch, "speakerops-demo")

    async def _roundtrip():
        import anyio
        from mcp.client.session import ClientSession
        from mcp.shared._context_streams import create_context_streams
        from mcp.shared.message import SessionMessage

        server = bridge.build_server()
        server_read_writer, server_read = create_context_streams[SessionMessage | Exception](0)
        server_write, server_write_reader = create_context_streams[SessionMessage](0)
        client_write, client_write_reader = create_context_streams[SessionMessage](0)
        client_read_writer, client_read = create_context_streams[SessionMessage | Exception](0)

        async def pump_client_to_server():
            try:
                async with client_write_reader:
                    async for message in client_write_reader:
                        await server_read_writer.send(message)
            except Exception:
                pass

        async def pump_server_to_client():
            try:
                async with server_write_reader:
                    async for message in server_write_reader:
                        await client_read_writer.send(message)
            except Exception:
                pass

        async def run_server():
            await server.run(
                server_read,
                server_write,
                server.create_initialization_options(),
                raise_exceptions=False,
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_server)
            tg.start_soon(pump_client_to_server)
            tg.start_soon(pump_server_to_client)
            async with ClientSession(read_stream=client_read, write_stream=client_write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 9
                assert {t.name for t in tools.tools} == set(ALL_BUZZ_READS.split(","))
                from mcp.shared.exceptions import MCPError

                with pytest.raises(MCPError) as exc_info:
                    await session.call_tool("bogus_tool", {})
                assert "bogus_tool" in str(exc_info.value)
                tg.cancel_scope.cancel()

    asyncio.run(_roundtrip())


@pytest.mark.django_db(transaction=True)
def test_content_readiness_reports_changes_requested_with_owner(event, users):
    with scope(event=event):
        changed_sub = event.submissions.first()
        changed_evidence = _session_changes_requested(event, users, changed_sub, users["speaker"])
        ready_sub = event.submissions.exclude(pk=changed_sub.pk).first()
        ready_evidence = _session_ready(event, users, ready_sub, users["reviewer"])

    result = content_readiness(event.slug, base_url="http://example.test")

    not_ready = {row["submission"]["pk"]: row for row in result["not_ready"]}
    row = not_ready[changed_sub.pk]
    assert row["state"] == "changes_requested"
    assert row["owner"] == users["chair"].get_display_name()
    item = next(i for i in row["items"] if i["state"] == "changes_requested")
    assert item["file_request"] == "Upload slides"
    assert item["note"] == "Add the licensing slide."
    assert item["latest_evidence"]["version"] == changed_evidence.version
    assert item["latest_evidence"]["url"] == (
        f"http://example.test/go/evidence-file/{event.slug}~{changed_evidence.pk}/"
    )

    ready = {row["submission"]["pk"]: row for row in result["ready"]}
    assert ready[ready_sub.pk]["state"] == "ready"
    assert all(i["state"] == "approved" for i in ready[ready_sub.pk]["items"])
    assert ready_evidence.version in {
        i["latest_evidence"]["version"] for i in ready[ready_sub.pk]["items"]
    }

    rollup = result["rollup"]
    assert rollup["ready"] + rollup["not_ready"] == rollup["sessions"]
    assert result["sources"]["console"] == f"http://example.test/go/content-console/{event.slug}/"
    assert result["sources"]["bundle"] == f"http://example.test/go/av-bundle/{event.slug}/"
    assert "generated_at" in result


@pytest.mark.django_db(transaction=True)
def test_content_readiness_flags_stale_superseded_approval(event, users):
    with scope(event=event):
        sub = event.submissions.first()
        _session_ready(event, users, sub, users["speaker"])
        task = OnboardingTask.objects.get(
            event=event, submission=sub, speaker=users["speaker"], definition__slug="slides"
        )
        second, _ = record_evidence(
            task,
            users["speaker"],
            "upload",
            upload=SimpleUploadedFile(
                "deck-v2.pdf", b"%PDF-1.7\nv2\n%%EOF", content_type="application/pdf"
            ),
        )

    result = content_readiness(event.slug, base_url="http://example.test")
    row = next(r for r in result["not_ready"] if r["submission"]["pk"] == sub.pk)
    assert row["state"] == "stale"
    item = next(i for i in row["items"] if i["stale"])
    assert item["latest_evidence"]["version"] == second.version
    assert item["latest_evidence"]["review_status"] == TaskEvidence.PENDING
    assert result["rollup"]["stale"] >= 1


@pytest.mark.django_db(transaction=True)
def test_content_readiness_flags_missing_file_request_with_speaker_owner(event, users):
    with scope(event=event):
        sub = event.submissions.first()
        event.enable_plugin("pretalx_speakerops")
        event.save()
        sub.speakers.set([users["speaker"]])
        sub.accept(person=users["chair"], force=True)
        ensure_acceptance_plan(sub)
        OnboardingTask.objects.get(
            event=event, submission=sub, speaker=users["speaker"], definition__slug="slides"
        )

    result = content_readiness(event.slug, base_url="http://example.test")
    row = next(r for r in result["not_ready"] if r["submission"]["pk"] == sub.pk)
    assert row["state"] == "missing"
    item = next(i for i in row["items"] if i["state"] == "missing")
    assert item["owner"] == users["speaker"].get_display_name()
    assert item["latest_evidence"] is None
    assert result["rollup"]["missing_file_requests"] >= 1


@pytest.mark.django_db(transaction=True)
def test_content_readiness_publication_gate_blocks_ready_session(event, users):
    with scope(event=event):
        sub = event.submissions.first()
        _session_ready(event, users, sub, users["speaker"])
        SessionPublicationApproval.objects.create(
            event=event, submission=sub, status=SessionPublicationApproval.PENDING
        )

    result = content_readiness(event.slug, base_url="http://example.test")
    row = next(r for r in result["not_ready"] if r["submission"]["pk"] == sub.pk)
    assert row["state"] == "publication_pending"
    assert row["owner"] == "not yet reviewed"
    assert result["rollup"]["publication_pending"] >= 1


@pytest.mark.django_db(transaction=True)
def test_content_readiness_includes_publication_gate_without_upload_tasks(event):
    with scope(event=event):
        sub = event.submissions.first()
        assert not OnboardingTask.objects.filter(event=event, submission=sub).exists()
        SessionPublicationApproval.objects.create(
            event=event,
            submission=sub,
            status=SessionPublicationApproval.PENDING,
            note="Awaiting copy approval.",
        )

    result = content_readiness(event.slug, base_url="http://example.test")
    row = next(r for r in result["not_ready"] if r["submission"]["pk"] == sub.pk)
    assert row["items"] == []
    assert row["state"] == "publication_pending"
    assert row["publication"]["note"] == "Awaiting copy approval."


@pytest.mark.django_db
def test_content_readiness_unknown_event_raises():
    with pytest.raises(KeyError):
        content_readiness("no-such-event")


@pytest.mark.django_db(transaction=True)
def test_content_readiness_message_formats_not_ready_sources_and_trace(event, users):
    with scope(event=event):
        sub = event.submissions.first()
        evidence = _session_changes_requested(event, users, sub, users["speaker"])

    message = content_readiness_message(event.slug, base_url="http://example.test")

    assert message.startswith(f"# Content readiness — {event.slug}")
    assert "**Not AV-ready**" in message
    assert "## Not AV-ready (owner)" in message
    assert users["chair"].get_display_name() in message
    assert "Add the licensing slide." in message
    assert (
        f"[evidence v{evidence.version}](http://example.test/go/evidence-file/"
        f"{event.slug}~{evidence.pk}/)" in message
    )
    assert "## AV-ready (" in message
    assert "## Rollup" in message
    assert "| ready |" in message

    assert "## Sources — canonical URL list" in message
    assert "| content-console |" in message
    assert "| av-bundle |" in message
    assert f"http://example.test/go/av-bundle/{event.slug}/" in message
    assert f"http://example.test/go/content-console/{event.slug}/" in message
    assert "| speakerops_content_operations | organiser | aggregate-screen |" in message

    assert "## Trace of inference" in message
    lines = message.splitlines()
    assert any(line.startswith("1. Resolved event") for line in lines)
    assert any(line.startswith("2. Read") and "upload file-request tasks" in line for line in lines)
    assert any(line.startswith("6. Built go/ links") for line in lines)
    assert any(line.startswith("7. Verdict:") and "not AV-ready" in line for line in lines)
    assert any("Generated " in line and "(ISO-8601)" in line for line in lines)


def test_render_content_readiness_clean_requires_no_db():
    message = render_content_readiness(
        {
            "event": "demo",
            "ready": [],
            "not_ready": [],
            "rollup": {
                "upload_tasks": 3,
                "sessions": 3,
                "ready": 3,
                "not_ready": 0,
                "missing_file_requests": 0,
                "pending_review": 0,
                "changes_requested": 0,
                "stale": 0,
                "publication_approved": 0,
                "publication_pending": 0,
                "publication_changes": 0,
            },
            "sources": {
                "console": "http://x/go/content-console/demo/",
                "evidence": "http://x/go/evidence-file/demo~{evidence_pk}/",
                "bundle": "http://x/go/av-bundle/demo/",
            },
            "generated_at": "2026-08-11T00:00:00+00:00",
        }
    )
    assert "**AV-ready** — all 3 sessions are ready." in message
    assert "## Not AV-ready (owner)" not in message
    assert "## AV-ready (0)" in message
    assert "Verdict: 0 of 3 sessions not AV-ready." in message


@pytest.mark.django_db(transaction=True)
def test_call_tool_content_readiness_returns_message(event, users, monkeypatch):
    _scope_bridge(monkeypatch, event.slug)
    with scope(event=event):
        sub = event.submissions.first()
        _session_changes_requested(event, users, sub, users["speaker"])

    params = CallToolRequestParams(
        name="content_readiness",
        arguments={"event_slug": event.slug},
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is not True
    text = result.content[0].text
    assert text.startswith(f"# Content readiness — {event.slug}")
    assert "## Sources — canonical URL list" in text
    assert "## Trace of inference" in text
    assert f"https://example.test/go/content-console/{event.slug}/" in text


@pytest.mark.django_db(transaction=True)
def test_call_tool_content_readiness_unknown_event_is_error(monkeypatch):
    _scope_bridge(monkeypatch, "missing-event")
    params = CallToolRequestParams(
        name="content_readiness", arguments={"event_slug": "missing-event"}
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert "missing-event" in result.content[0].text


@pytest.mark.django_db(transaction=True)
def test_conference_memory_reports_verified_recurrence_sources_and_exact_links(event):
    speaker = _arrange_verified_conference_memory()

    result = conference_memory(event.slug, query="Agent", base_url="https://example.test")

    assert result["matching_talks"] == 2
    assert result["corpus"] == {
        "series": 1,
        "editions": 2,
        "talks": 2,
        "speaker_credits": 2,
        "source_identities": 2,
        "people": 1,
    }
    assert result["scope"] == {
        "query_applied": True,
        "matching_talks": 2,
        "corpus_totals_are_unfiltered": True,
    }
    assert result["aie_corpus"] == {
        "talks": 2,
        "editions": 2,
        "missing_format": 0,
        "missing_track": 1,
    }
    assert result["corpus_gaps"] == {"missing_format": 0, "missing_track": 1}
    assert result["missing_metadata_is_not_inferred"] is True
    assert result["aie"]["missing_track"] == 1
    assert result["topic_signals"] == [
        {"label": "Agents", "aie": 2, "peers": 0},
        {"label": "Evals", "aie": 2, "peers": 0},
    ]
    assert len(result["evidence_sample"]) == 2
    assert {row["title"] for row in result["evidence_sample"]} == {
        "Agent Evals in 2024",
        "Agent Evals in 2025",
    }
    assert all(
        row["source_url"].startswith("https://www.ai.engineer/")
        for row in result["evidence_sample"]
    )
    assert any(row["track"] == SOURCE_NOT_PROVIDED for row in result["evidence_sample"])
    returning = result["returning_speakers"]
    assert len(returning) == 1
    assert returning[0]["speaker_pk"] == speaker.pk
    assert returning[0]["edition_count"] == 2
    assert len(returning[0]["verified_sources"]) == 2
    assert returning[0]["link"] == (
        f"https://example.test/go/conference-speaker/{event.slug}~{speaker.pk}/"
    )
    assert result["links"]["memory"] == (f"https://example.test/go/conference-memory/{event.slug}/")
    assert result["links"]["crm"] == (
        f"https://example.test/go/crm-directory/{event.organiser.slug}/"
    )

    message = conference_memory_message(event.slug, query="Agent", base_url="https://example.test")
    assert "# Conference Memory" in message
    assert "Verified returning AIE speakers" in message
    assert "Returning Builder" in message
    assert "## What the evidence says" in message
    assert "Full evidence corpus (unfiltered):** 1 series" in message
    assert "Query-matched subset" in message
    assert "Format frequency in the matching evidence" in message
    assert "Track frequency in the matching evidence" in message
    assert "Agent Evals in 2024" in message
    assert "programming-memory signals, not acceptance recommendations" in message
    assert "Missing metadata and unverified identity recurrence are never inferred" in message
    assert "https://www.ai.engineer/worldsfair/2024/speakers/returning-builder" in message
    assert "## Trace of inference" in message

    unfiltered_message = conference_memory_message(event.slug, base_url="https://example.test")
    assert "Query-matched subset" not in unfiltered_message
    assert unfiltered_message.count("- Full AIE corpus:") == 1


@pytest.mark.django_db(transaction=True)
def test_conference_memory_recurrence_is_scoped_to_matching_verified_aie_credits(event):
    speaker = _arrange_verified_conference_memory()
    updated = timezone.now()
    aie = ConferenceSeries.objects.get(slug="ai-engineer")
    unrelated = HistoricalSpeaker.objects.create(
        canonical_key="unrelated-returner",
        name="Unrelated Returner",
        source_url="https://www.ai.engineer/speakers/unrelated-returner",
        source_updated_at=updated,
    )
    for edition in ConferenceEdition.objects.filter(series=aie).order_by("date_from"):
        identity = HistoricalSourceIdentity.objects.create(
            edition=edition,
            source_key=f"unrelated-returner-{edition.external_key}",
            speaker=unrelated,
            display_name=unrelated.name,
            source_url=(
                f"https://www.ai.engineer/{edition.external_key}/speakers/unrelated-returner"
            ),
            source_updated_at=updated,
            resolution_status=HistoricalSourceIdentity.VERIFIED,
        )
        talk = HistoricalTalk.objects.create(
            edition=edition,
            external_key=f"kubernetes-{edition.external_key}",
            title=f"Kubernetes Operations in {edition.external_key}",
            session_format="Talk",
            track="Infrastructure",
            source_url=f"https://www.ai.engineer/{edition.external_key}/kubernetes",
            source_updated_at=updated,
        )
        talk.speakers.add(unrelated)
        HistoricalSpeakerCredit.objects.create(
            talk=talk,
            speaker=unrelated,
            source_identity=identity,
            name_at_source=unrelated.name,
            source_url=identity.source_url,
            source_updated_at=updated,
        )

    peer = ConferenceSeries.objects.create(
        slug="peer-conf",
        name="Peer Conf",
        website="https://peer.example/",
    )
    peer_edition = ConferenceEdition.objects.create(
        series=peer,
        external_key="2025",
        name="Peer Conf 2025",
        date_from=date(2025, 9, 1),
        source_url="https://peer.example/2025/",
        source_updated_at=updated,
    )
    peer_talk = HistoricalTalk.objects.create(
        edition=peer_edition,
        external_key="agent-peer",
        title="Agent Evals at Peer Conf",
        session_format="Talk",
        source_url="https://peer.example/2025/agent-peer",
        source_updated_at=updated,
    )
    peer_talk.speakers.add(speaker)
    HistoricalSpeakerCredit.objects.create(
        talk=peer_talk,
        speaker=speaker,
        name_at_source=speaker.name,
        source_url=peer_talk.source_url,
        source_updated_at=updated,
    )

    result = conference_memory(event.slug, query="Agent", base_url="https://example.test")
    assert [row["name"] for row in result["returning_speakers"]] == ["Returning Builder"]
    assert result["returning_speakers"][0]["appearance_count"] == 2
    assert result["returning_speakers"][0]["edition_count"] == 2
    assert len(result["returning_speakers"][0]["verified_sources"]) == 2

    one_edition = conference_memory(
        event.slug,
        query="Agent Evals in 2024",
        base_url="https://example.test",
    )
    assert one_edition["matching_talks"] == 1
    assert one_edition["returning_speakers"] == []


@pytest.mark.django_db(transaction=True)
def test_call_tool_conference_memory_is_scoped_and_grounded(event, monkeypatch):
    _arrange_verified_conference_memory()
    _scope_bridge(monkeypatch, event.slug)
    params = CallToolRequestParams(
        name="conference_memory",
        arguments={"event_slug": event.slug, "query": "Agent"},
    )

    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is not True
    text = result.content[0].text
    assert "2 sourced talks across 2 editions" in text
    assert "Returning Builder" in text
    assert f"https://example.test/go/conference-memory/{event.slug}/" in text


@pytest.mark.django_db(transaction=True)
def test_conference_memory_rejects_oversized_query(event):
    with pytest.raises(ValueError, match="at most 160"):
        conference_memory(event.slug, query="x" * 161)
