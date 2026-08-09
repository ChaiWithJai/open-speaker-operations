import pytest
from django.urls import reverse
from django_scopes import scope


def _prepare_roles(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.assigned_reviewers.add(users["reviewer"])
    return submission


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("role", "destination"),
    (
        ("speaker", "speakerops_checklist"),
        ("reviewer", "speakerops_review_queue"),
        ("chair", "speakerops_dashboard"),
    ),
)
def test_role_entry_routes_each_identity_to_its_home(event, users, client, role, destination):
    _prepare_roles(event, users)
    client.force_login(users[role])

    response = client.get(
        reverse("plugins:speakerops:speakerops_entry", kwargs={"event": event.slug})
    )

    assert response.status_code == 302
    assert response.url == reverse(
        f"plugins:speakerops:{destination}", kwargs={"event": event.slug}
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("role", "login_name", "destination"),
    (
        ("speaker", "cfp:event.login", "speakerops_checklist"),
        ("reviewer", "orga:event.login", "speakerops_review_queue"),
        ("chair", "orga:event.login", "speakerops_dashboard"),
    ),
)
def test_event_login_lands_each_identity_at_role_home(
    event, users, client, role, login_name, destination
):
    _prepare_roles(event, users)

    response = client.post(
        reverse(login_name, kwargs={"event": event.slug}),
        {"login_email": users[role].email, "login_password": "test-password"},
        follow=True,
    )

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == reverse(
        f"plugins:speakerops:{destination}", kwargs={"event": event.slug}
    )


@pytest.mark.django_db(transaction=True)
def test_role_navigation_is_named_current_and_permission_filtered(event, users, client):
    _prepare_roles(event, users)

    client.force_login(users["speaker"])
    checklist = client.get(
        reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event.slug})
    )
    checklist_body = checklist.content.decode()
    assert 'aria-label="Speaker Operations"' in checklist_body
    assert checklist.context["speakerops_navigation"][0]["active"]
    assert "aria-current=page" in checklist_body
    assert ">Speaker tasks</a>" in checklist_body
    assert "Back to your proposals" in checklist_body
    assert (
        client.get(
            reverse("plugins:speakerops:speakerops_review_queue", kwargs={"event": event.slug})
        ).status_code
        == 404
    )

    client.force_login(users["reviewer"])
    review = client.get(
        reverse("plugins:speakerops:speakerops_review_queue", kwargs={"event": event.slug})
    )
    review_body = review.content.decode()
    assert 'aria-label="Speaker Operations"' in review_body
    assert any(
        item["label"] == "Review queue" and item["active"]
        for item in review.context["speakerops_navigation"]
    )
    assert sum(item["active"] for item in review.context["speakerops_navigation"]) == 1
    assert ">Operations</a>" not in review_body
    assert ">Agenda / release</a>" not in review_body
    assert ">Sync</a>" not in review_body
    assert (
        client.get(
            reverse("plugins:speakerops:speakerops_sync_console", kwargs={"event": event.slug})
        ).status_code
        == 404
    )

    client.force_login(users["chair"])
    dashboard = client.get(
        reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event.slug})
    )
    dashboard_body = dashboard.content.decode()
    assert any(
        item["label"] == "Operations" and item["active"]
        for item in dashboard.context["speakerops_navigation"]
    )
    for label in ("Review queue", "Agenda / release", "Sync"):
        assert f">{label}</a>" in dashboard_body
    assert ">Speaker tasks</a>" not in dashboard_body


@pytest.mark.django_db(transaction=True)
def test_explicit_login_return_path_is_preserved(event, users, client):
    _prepare_roles(event, users)
    destination = reverse(
        "plugins:speakerops:speakerops_review_queue", kwargs={"event": event.slug}
    )

    response = client.post(
        reverse("orga:event.login", kwargs={"event": event.slug}) + f"?next={destination}",
        {
            "login_email": users["reviewer"].email,
            "login_password": "test-password",
        },
    )

    assert response.status_code == 302
    assert response.url == destination
