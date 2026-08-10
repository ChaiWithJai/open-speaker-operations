import pytest
from django.urls import reverse
from django_scopes import scope
from pretalx.event.models import TeamInvite
from pretalx.person.models import User


@pytest.mark.django_db(transaction=True)
def test_reviewer_invite_creates_usable_scoped_account(event, users, client):
    """CFP-10: provision a reviewer, accept the invite, and prove role isolation."""
    reviewer_email = "sam-whitfield@example.org"
    reviewer_password = "reviewer-test-password-2026"
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        chair_team = users["chair"].teams.get(organiser=event.organiser)
        chair_team.can_change_teams = True
        chair_team.save(update_fields=["can_change_teams", "updated"])
        reviewer_team = users["reviewer"].teams.get(organiser=event.organiser)

    client.force_login(users["chair"])
    team_url = reverse(
        "orga:organiser.teams.update",
        kwargs={"organiser": event.organiser.slug, "pk": reviewer_team.pk},
    )
    team_page = client.get(team_url)
    invite_response = client.post(
        team_url,
        {
            "form": "invite",
            "invite-email": reviewer_email,
            "invite-bulk_email": "",
        },
        follow=True,
    )

    assert team_page.status_code == 200
    assert b"name=invite-email" in team_page.content
    assert invite_response.status_code == 200
    assert b"The invitation has been sent." in invite_response.content
    invite = TeamInvite.objects.get(team=reviewer_team, email=reviewer_email)

    client.logout()
    invitation_url = reverse("orga:invitation.view", kwargs={"code": invite.token})
    invitation_page = client.get(invitation_url)

    assert invitation_page.status_code == 200
    assert b"name=register_email" in invitation_page.content
    assert b"name=register_password" in invitation_page.content

    accepted = client.post(
        invitation_url,
        {
            "register_name": "Sam Whitfield",
            "register_email": reviewer_email,
            "register_password": reviewer_password,
            "register_password_repeat": reviewer_password,
        },
    )

    assert accepted.status_code == 302
    reviewer = User.objects.get(email=reviewer_email)
    assert reviewer_team.members.filter(pk=reviewer.pk).exists()
    assert not TeamInvite.objects.filter(pk=invite.pk).exists()

    review_queue = client.get(
        reverse("plugins:speakerops:speakerops_review_queue", kwargs={"event": event.slug})
    )
    review_body = review_queue.content.decode()

    assert review_queue.status_code == 200
    assert "Review queue" in review_body
    assert "Speaker Operations global navigation" in review_body
    assert ">Operations</a>" not in review_body
    assert ">Agenda / release</a>" not in review_body
    assert ">Sync</a>" not in review_body
    assert (
        client.get(
            reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event.slug})
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("plugins:speakerops:speakerops_sync_console", kwargs={"event": event.slug})
        ).status_code
        == 404
    )
