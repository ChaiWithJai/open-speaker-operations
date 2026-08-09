import pytest
from django_scopes import scope
from pretalx.submission.models import Submission, SubmissionStates

from pretalx_speakerops.models import ProgramDecision
from pretalx_speakerops.simulation import simulate_cfp


@pytest.mark.django_db(transaction=True)
def test_cfp_scale_simulation_runs_review_decision_and_onboarding_path(event):
    result = simulate_cfp(event, speaker_count=30, acceptance_rate=0.10)

    assert result.speakers == 30
    assert result.proposals == 30
    assert result.reviewers == 1
    assert result.reviews == 30
    assert result.accepted == 3
    assert result.waitlisted == 2
    assert result.rejected == 25
    with scope(event=event):
        proposals = Submission.objects.filter(title__startswith="Scale proposal")
        assert proposals.count() == 30
        assert proposals.filter(state=SubmissionStates.ACCEPTED).count() == 3
        assert proposals.filter(track__isnull=False).count() == 30
        assert all(
            proposal.answers.filter(question__question="Audience level").exists()
            for proposal in proposals
        )
        assert all(
            proposal.answers.filter(question__question="Key takeaway").exists()
            for proposal in proposals
        )
        assert all(
            proposal.answers.filter(question__question="Session abstract").exists()
            for proposal in proposals
        )
        assert ProgramDecision.objects.filter(event=event, submission__in=proposals).count() == 30
        assert (
            ProgramDecision.objects.filter(
                event=event,
                submission__in=proposals,
                status=ProgramDecision.ACCEPT,
                applied_at__isnull=False,
                applied_by__isnull=False,
            ).count()
            == 3
        )
        assert proposals.filter(state=SubmissionStates.REJECTED).count() == 25


@pytest.mark.django_db(transaction=True)
def test_cfp_scale_supports_multiple_proposals_and_explicit_reviewer_capacity(event):
    result = simulate_cfp(
        event,
        speaker_count=12,
        proposal_count=24,
        reviewer_count=4,
        acceptance_rate=0.125,
    )

    assert result.speakers == 12
    assert result.proposals == 24
    assert result.reviewers == 4
    assert result.reviews == 24
    assert result.accepted == 3
    with scope(event=event):
        proposals = Submission.objects.filter(title__startswith="Scale proposal")
        assert proposals.count() == 24
        assert proposals.filter(speakers__isnull=False).distinct().count() == 24
        assert proposals.filter(assigned_reviewers__isnull=False).distinct().count() == 24
