import json
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest
from django_scopes import scope

from mock_accelevents.server import Handler, state
from pretalx_speakerops.integrations.accelevents import AcceleventsClient, AcceleventsError
from pretalx_speakerops.integrations.sync import execute_item, execute_preview, preview
from pretalx_speakerops.models import (
    AcceleventsConnection,
    ExternalIdentity,
    SyncItem,
)


@pytest.fixture
def mock_url():
    state["speakers"].clear()
    state["sessions"].clear()
    state["writes"] = 0
    state["next_speaker"] = 1
    state["next_session"] = 1
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.django_db(transaction=True)
def test_mock_contract_auth_duplicate_and_bare_integer(mock_url):
    client = AcceleventsClient(mock_url, "demo", "demo-key")
    fixture_dir = Path(__file__).parent / "fixtures" / "accelevents"
    speaker_payload = json.loads((fixture_dir / "create-speaker-request.json").read_text())
    speaker_id = client.create_speaker(speaker_payload)
    assert isinstance(speaker_id, int)
    with pytest.raises(AcceleventsError) as error:
        client.create_speaker(speaker_payload)
    assert error.value.code == 4068906
    assert client.speakers_with_sessions()[0]["id"] == speaker_id
    with pytest.raises(AcceleventsError) as error:
        AcceleventsClient(mock_url, "demo", "wrong").speakers_with_sessions()
    assert error.value.status == 401
    session_payload = json.loads((fixture_dir / "create-session-request.json").read_text())
    session_id = client.create_session({**session_payload, "speakerId": speaker_id})
    assert isinstance(session_id, int)
    assert client.update_session(session_id, {**session_payload, "title": "Updated"}) is None
    assert client.update_speaker(speaker_id, {**speaker_payload, "bio": "Updated"}) is None

    locked_id = client.create_speaker(
        {**speaker_payload, "email": "locked@example.org", "loggedIn": True}
    )
    with pytest.raises(AcceleventsError) as error:
        client.update_speaker(locked_id, {**speaker_payload, "email": "changed@example.org"})
    assert error.value.code == 4090121


@pytest.mark.django_db(transaction=True)
def test_partial_run_retry_does_not_resend_successful_item(event, users, mock_url):
    with scope(event=event):
        AcceleventsConnection.objects.create(
            event=event,
            base_url=mock_url,
            event_url="demo",
            credential_ref="demo-key",
            status=AcceleventsConnection.STATUS_CONNECTED,
        )
        payloads = [
            ("speaker", 9101, {"email": "one@example.org", "firstName": "One"}),
            ("speaker", 9102, {"email": "two@example.org", "firstName": "Two"}),
        ]
        sync_preview = preview(event, payloads)
        run = execute_preview(event, sync_preview.pk, users["chair"])
        import mock_accelevents.server as mock

        mock.FAIL_EMAIL = "two@example.org"
        execute_item(run.items.order_by("pk").first(), users["chair"])
        failed = run.items.order_by("pk").last()
        execute_item(failed, users["chair"])
        assert ExternalIdentity.objects.filter(event=event).count() == 1
        mock.FAIL_EMAIL = ""
        execute_item(failed, users["chair"])
        failed.refresh_from_db()
        assert failed.status == SyncItem.SUCCEEDED, failed.error
        assert ExternalIdentity.objects.filter(event=event).count() == 2
        assert failed.attempts == 2
        assert failed.status == SyncItem.SUCCEEDED


@pytest.mark.django_db(transaction=True)
def test_update_then_preview_is_noop_and_stale_preview_is_rejected(event, users, mock_url):
    with scope(event=event):
        AcceleventsConnection.objects.create(
            event=event,
            base_url=mock_url,
            event_url="demo",
            credential_ref="demo-key",
            status=AcceleventsConnection.STATUS_CONNECTED,
        )
        payload = {"email": "update@example.org", "firstName": "Before"}
        external = AcceleventsClient(mock_url, "demo", "demo-key").create_speaker(payload)
        ExternalIdentity.objects.create(
            event=event,
            local_type="speaker",
            local_id=999,
            external_id=str(external),
            request_fingerprint="stale",
        )
        update_preview = preview(event, [("speaker", 999, {**payload, "bio": "new"})])
        run = execute_preview(event, update_preview.pk, users["chair"])
        item = run.items.get()
        assert item.action == "update"
        execute_item(item, users["chair"])
        assert (
            preview(event, [("speaker", 999, {**payload, "bio": "new"})]).payload["items"][0][
                "action"
            ]
            == "noop"
        )

        live_payload = {
            "firstName": (users["speaker"].name or "Demo Speaker").split(" ", 1)[0],
            "lastName": (users["speaker"].name or "Demo Speaker").split(" ", 1)[-1],
            "email": users["speaker"].email,
        }
        stale = preview(event, [("speaker", users["speaker"].pk, live_payload)])
        users["speaker"].email = "changed-live@example.org"
        users["speaker"].save(update_fields=["email"])
        with pytest.raises(ValueError, match="Preview is stale"):
            execute_preview(event, stale.pk, users["chair"])
