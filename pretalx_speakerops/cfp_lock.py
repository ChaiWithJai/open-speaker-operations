from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone

CLOSED_CFP_MESSAGE = (
    "The call for proposals is closed. This proposal is read-only; "
    "contact the organisers if a correction is required."
)


def proposal_mutations_open(submission):
    """Return whether a speaker may still mutate proposal-owned data."""

    deadline = submission.submission_type.deadline or submission.event.cfp.deadline
    return deadline is None or timezone.now() <= deadline


def require_open_proposal(submission):
    if not proposal_mutations_open(submission):
        raise PermissionDenied(CLOSED_CFP_MESSAGE)


def install_closed_cfp_guards():
    """Protect native pretalx speaker mutation endpoints after the CFP deadline."""

    from pretalx.cfp.views.user import (
        SubmissionDraftDiscardView,
        SubmissionInviteAcceptView,
        SubmissionInviteView,
        SubmissionsEditView,
        SubmissionsWithdrawView,
    )

    if getattr(SubmissionsEditView, "_speakerops_closed_cfp_guard", False):
        return

    original_edit_dispatch = SubmissionsEditView.dispatch

    @wraps(original_edit_dispatch)
    def edit_dispatch(view, request, *args, **kwargs):
        if request.user.is_authenticated and not proposal_mutations_open(view.object):
            messages.info(request, CLOSED_CFP_MESSAGE)
        return original_edit_dispatch(view, request, *args, **kwargs)

    SubmissionsEditView.dispatch = edit_dispatch

    for view_class in (
        SubmissionsWithdrawView,
        SubmissionDraftDiscardView,
        SubmissionInviteView,
    ):
        original_post = view_class.post

        @wraps(original_post)
        def guarded_post(view, request, *args, _original=original_post, **kwargs):
            require_open_proposal(view.get_object())
            return _original(view, request, *args, **kwargs)

        view_class.post = guarded_post

    original_accept_post = SubmissionInviteAcceptView.post

    @wraps(original_accept_post)
    def guarded_accept_post(view, request, *args, **kwargs):
        require_open_proposal(view.get_object())
        return original_accept_post(view, request, *args, **kwargs)

    SubmissionInviteAcceptView.post = guarded_accept_post
    SubmissionsEditView._speakerops_closed_cfp_guard = True
