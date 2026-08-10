import pytest
from django import forms
from django.urls import reverse
from django_scopes import scope
from pretalx.event.models import Team
from pretalx.person.models import User
from pretalx.submission.models import Submission, SubmissionStates, Track

from pretalx_speakerops.cfp import (
    SpeakerOpsQuestionsForm,
    configure_demo_cfp_routing,
)
from pretalx_speakerops.models import (
    ConditionalQuestionRule,
    ReviewerPoolTrack,
)


def _configure_routing(event, users):
    second = User.objects.create_user(
        email="second-reviewer@example.org",
        name="Second Reviewer",
        password="test-password",
    )
    team = Team.objects.get(organiser=event.organiser, is_reviewer=True, members=users["reviewer"])
    team.members.add(second)
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        pools = configure_demo_cfp_routing(event, (users["reviewer"], second))
    return pools, second


def _valid_form_data(event, *, relationship, context=None, submission_type=None):
    prototype = SpeakerOpsQuestionsForm(
        event=event, submission_type=submission_type or event.cfp.default_type
    )
    data = {}
    for name, field in prototype.fields.items():
        if not field.required:
            continue
        if isinstance(field, forms.ModelMultipleChoiceField):
            data[name] = [field.queryset.first().pk]
        elif isinstance(field, forms.ModelChoiceField):
            data[name] = field.queryset.first().pk
        elif isinstance(field, forms.BooleanField):
            data[name] = "on"
        else:
            data[name] = "A sufficiently detailed answer for deterministic policy testing."
    relationship_question = event.questions.get(question="Commercial relationship")
    data[f"question_{relationship_question.pk}"] = relationship_question.options.get(
        answer=relationship
    ).pk
    context_question = event.questions.get(question="Proposed session context")
    if context:
        data[f"question_{context_question.pk}"] = context_question.options.get(answer=context).pk
    else:
        data.pop(f"question_{context_question.pk}", None)
    topics_question = event.questions.get(question="Topics")
    data[f"question_{topics_question.pk}"] = [topics_question.options.first().pk]
    return data


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("topic_count", "expected_valid"),
    ((0, False), (1, True), (5, True), (6, False)),
)
def test_submission_form_enforces_one_to_five_topics(event, users, topic_count, expected_valid):
    with scope(event=event):
        pools, _second = _configure_routing(event, users)
        track = pools[0].track_mappings.first().track
        proposal = _proposal(event, users, track)
        data = _valid_form_data(
            event,
            relationship="No commercial relationship",
            submission_type=proposal.submission_type,
        )
        topics = event.questions.get(question="Topics")
        data[f"question_{topics.pk}"] = list(
            topics.options.order_by("position").values_list("pk", flat=True)[:topic_count]
        )
        form = SpeakerOpsQuestionsForm(
            data=data,
            event=event,
            submission=proposal,
            submission_type=proposal.submission_type,
            track=proposal.track,
            speaker=users["speaker"],
        )

        assert form.is_valid() is expected_valid
        if not expected_valid:
            assert "one and five topics" in str(form.errors[f"question_{topics.pk}"])


def _proposal(event, users, track):
    proposal = Submission.objects.create(
        event=event,
        title="Conditional routing test",
        abstract="A concrete abstract for routing validation.",
        description="A concrete description for routing validation.",
        submission_type=event.submission_types.get(name="Workshop"),
        track=track,
        state=SubmissionStates.SUBMITTED,
        content_locale=event.locale,
    )
    proposal.speakers.add(users["speaker"])
    return proposal


@pytest.mark.django_db(transaction=True)
def test_both_conditional_branches_route_to_distinct_reviewer_pools(event, users):
    with scope(event=event):
        pools, second = _configure_routing(event, users)
        tracks = list(event.tracks.order_by("position", "pk"))
        first_track = pools[0].track_mappings.first().track
        second_track = pools[1].track_mappings.first().track

        ordinary = _proposal(event, users, first_track)
        ordinary_form = SpeakerOpsQuestionsForm(
            data=_valid_form_data(
                event,
                relationship="No commercial relationship",
                submission_type=ordinary.submission_type,
            ),
            event=event,
            submission=ordinary,
            submission_type=ordinary.submission_type,
            track=ordinary.track,
            speaker=users["speaker"],
        )
        assert ordinary_form.is_valid(), ordinary_form.errors
        ordinary_form.save()
        assert list(ordinary.assigned_reviewers.all()) == [users["reviewer"]]

        vendor = _proposal(event, users, second_track)
        vendor_form = SpeakerOpsQuestionsForm(
            data=_valid_form_data(
                event,
                relationship="I work for or represent a vendor discussed in this session",
                context="Workshop",
                submission_type=vendor.submission_type,
            ),
            event=event,
            submission=vendor,
            submission_type=vendor.submission_type,
            track=vendor.track,
            speaker=users["speaker"],
        )
        assert vendor_form.is_valid(), vendor_form.errors
        vendor_form.save()
        assert list(vendor.assigned_reviewers.all()) == [second]
        assert len(tracks) >= 2


@pytest.mark.django_db(transaction=True)
def test_server_rejects_hidden_field_and_unmapped_category_tampering(event, users):
    with scope(event=event):
        pools, _second = _configure_routing(event, users)
        mapped_track = pools[0].track_mappings.first().track
        tampered = _proposal(event, users, mapped_track)
        tampered_form = SpeakerOpsQuestionsForm(
            data=_valid_form_data(
                event,
                relationship="No commercial relationship",
                context="Workshop",
                submission_type=tampered.submission_type,
            ),
            event=event,
            submission=tampered,
            submission_type=tampered.submission_type,
            track=tampered.track,
            speaker=users["speaker"],
        )
        assert not tampered_form.is_valid()
        target = event.questions.get(question="Proposed session context")
        assert "hidden question" in str(tampered_form.errors[f"question_{target.pk}"])

        unmapped_track = Track.objects.create(event=event, name="Unmapped category")
        unroutable = _proposal(event, users, unmapped_track)
        unroutable_form = SpeakerOpsQuestionsForm(
            data=_valid_form_data(
                event,
                relationship="No commercial relationship",
                submission_type=unroutable.submission_type,
            ),
            event=event,
            submission=unroutable,
            submission_type=unroutable.submission_type,
            track=unmapped_track,
            speaker=users["speaker"],
        )
        assert not unroutable_form.is_valid()
        assert "unambiguous reviewer pool" in str(unroutable_form.non_field_errors())


@pytest.mark.django_db(transaction=True)
def test_vendor_branch_requires_the_revealed_question(event, users):
    with scope(event=event):
        pools, _second = _configure_routing(event, users)
        track = pools[1].track_mappings.first().track
        proposal = _proposal(event, users, track)
        form = SpeakerOpsQuestionsForm(
            data=_valid_form_data(
                event,
                relationship="I work for or represent a vendor discussed in this session",
                submission_type=proposal.submission_type,
            ),
            event=event,
            submission=proposal,
            submission_type=proposal.submission_type,
            track=proposal.track,
            speaker=users["speaker"],
        )
        assert not form.is_valid()
        target = event.questions.get(question="Proposed session context")
        assert "required for your previous answer" in str(form.errors[f"question_{target.pk}"])


@pytest.mark.django_db(transaction=True)
def test_chair_can_configure_rule_and_reviewer_pool_without_source_edits(event, users, client):
    with scope(event=event):
        pools, second = _configure_routing(event, users)
        rule = ConditionalQuestionRule.objects.get(event=event)
        pool = pools[0]
        chosen_tracks = list(pool.track_mappings.values_list("track_id", flat=True))
        controller = rule.controller_question
        target = rule.target_question
        trigger = rule.trigger_option

    client.force_login(users["chair"])
    url = reverse("plugins:speakerops:speakerops_cfp_routing", kwargs={"event": event.slug})
    page = client.get(url)
    assert page.status_code == 200
    assert b"Conditional questions" in page.content
    assert b"reviewer routing" in page.content

    rule_response = client.post(
        url,
        {
            "action": "save_rule",
            "rule_id": rule.pk,
            "name": "Commercial disclosure branch",
            "controller_question": controller.pk,
            "trigger_option": trigger.pk,
            "target_question": target.pk,
            "target_required_on_match": "on",
            "active": "on",
        },
    )
    assert rule_response.status_code == 302
    rule.refresh_from_db()
    assert rule.name == "Commercial disclosure branch"

    pool_response = client.post(
        url,
        {
            "action": "save_pool",
            "pool_id": pool.pk,
            "name": "Program policy reviewers",
            "slug": pool.slug,
            "tracks": chosen_tracks,
            "reviewers": [users["reviewer"].pk, second.pk],
        },
    )
    assert pool_response.status_code == 302
    pool.refresh_from_db()
    assert pool.name == "Program policy reviewers"
    assert set(pool.reviewers.all()) == {users["reviewer"], second}
    with scope(event=event):
        assert ReviewerPoolTrack.objects.filter(event=event).count() == len(event.tracks.all())

    client.force_login(users["reviewer"])
    assert client.get(url).status_code == 404
