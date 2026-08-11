import asyncio
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django_scopes import scope
from mcp.types import CallToolRequestParams, RequestParams

from pretalx_speakerops.buzz_reads import (
    content_readiness,
    content_readiness_message,
    release_readiness,
    release_readiness_message,
    render_content_readiness,
    render_release_readiness,
)
from pretalx_speakerops.models import OnboardingTask, SessionPublicationApproval, TaskEvidence
from pretalx_speakerops.onboarding.services import record_evidence
from tools import mcp_speakerops_server as bridge


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


def _make_session_content(event, users, submission, speaker, slides_action="approve", slides_note=""):
    """Give a session upload evidence for every upload file request.

    Everything is approved except slides, which takes ``slides_action``
    (``approve`` or ``request-changes``). Returns ``{slug: evidence}``.
    """
    submission.speakers.add(speaker)
    submission.accept(person=users["chair"], force=True)
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
    assert "release-blocking." in message

    assert "## Sources — canonical URL list" in message
    assert "pretalx_speakerops/canonical_links.py" in message
    assert (
        f"http://example.test/go/conflicts-drilldown/{event.slug}~conflicts/"
        in message
    )
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


def test_list_tools_exposes_release_readiness_schema():
    result = asyncio.run(bridge._handle_list_tools(None, RequestParams()))
    assert len(result.tools) == 2
    tool = next(t for t in result.tools if t.name == "release_readiness")
    assert tool.input_schema["required"] == ["event_slug"]
    assert "event_slug" in tool.input_schema["properties"]
    content = next(t for t in result.tools if t.name == "content_readiness")
    assert content.input_schema["required"] == ["event_slug"]
    assert "event_slug" in content.input_schema["properties"]


@pytest.mark.django_db(transaction=True)
def test_call_tool_returns_release_readiness_message(event):
    params = CallToolRequestParams(
        name="release_readiness",
        arguments={"event_slug": event.slug, "base_url": "http://example.test"},
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is not True
    text = result.content[0].text
    assert text.startswith(f"# Release readiness — {event.slug}")
    assert "## Sources — canonical URL list" in text
    assert "## Trace of inference" in text
    assert f"http://example.test/go/operations-dashboard/{event.slug}/" in text
    assert "Generated " in text


@pytest.mark.django_db(transaction=True)
def test_call_tool_unknown_event_is_error():
    params = CallToolRequestParams(
        name="release_readiness", arguments={"event_slug": "missing-event"}
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert "missing-event" in result.content[0].text


def test_call_tool_unknown_tool_raises():
    params = CallToolRequestParams(name="bogus_tool", arguments={})
    with pytest.raises(ValueError):
        asyncio.run(bridge._handle_call_tool(None, params))


def test_call_tool_in_process_protocol_roundtrip():
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
            async with ClientSession(
                read_stream=client_read, write_stream=client_write
            ) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 2
                assert {t.name for t in tools.tools} == {"release_readiness", "content_readiness"}
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
    assert ready_evidence.version in {i["latest_evidence"]["version"] for i in ready[ready_sub.pk]["items"]}

    rollup = result["rollup"]
    assert rollup["ready"] + rollup["not_ready"] == rollup["sessions"]
    assert result["sources"]["console"] == f"http://example.test/go/content-console/{event.slug}/"
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
        sub.speakers.add(users["speaker"])
        sub.accept(person=users["chair"], force=True)
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
            },
            "generated_at": "2026-08-11T00:00:00+00:00",
        }
    )
    assert "**AV-ready** — all 3 sessions are ready." in message
    assert "## Not AV-ready (owner)" not in message
    assert "## AV-ready (0)" in message
    assert "Verdict: 0 of 3 sessions not AV-ready." in message


@pytest.mark.django_db(transaction=True)
def test_call_tool_content_readiness_returns_message(event, users):
    with scope(event=event):
        sub = event.submissions.first()
        _session_changes_requested(event, users, sub, users["speaker"])

    params = CallToolRequestParams(
        name="content_readiness",
        arguments={"event_slug": event.slug, "base_url": "http://example.test"},
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is not True
    text = result.content[0].text
    assert text.startswith(f"# Content readiness — {event.slug}")
    assert "## Sources — canonical URL list" in text
    assert "## Trace of inference" in text
    assert f"http://example.test/go/content-console/{event.slug}/" in text


@pytest.mark.django_db(transaction=True)
def test_call_tool_content_readiness_unknown_event_is_error():
    params = CallToolRequestParams(
        name="content_readiness", arguments={"event_slug": "missing-event"}
    )
    result = asyncio.run(bridge._handle_call_tool(None, params))

    assert result.is_error is True
    assert "missing-event" in result.content[0].text
