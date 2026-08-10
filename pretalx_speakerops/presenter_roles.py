from .models import SubmissionPresenterRole


def presenter_rows(submission):
    """Return attached native presenters with persisted role labels."""
    roles = {
        item.speaker_id: item
        for item in submission.speakerops_presenter_roles.select_related("speaker")
    }
    rows = []
    for speaker in submission.speakers.all():
        role = roles.get(speaker.pk)
        rows.append(
            {
                "speaker": speaker,
                "role": role.role if role else "",
                "role_label": role.get_role_display() if role else "Presenter",
            }
        )
    priority = {
        SubmissionPresenterRole.PRIMARY_AUTHOR: 0,
        SubmissionPresenterRole.CO_AUTHOR: 1,
        SubmissionPresenterRole.CO_PRESENTER: 2,
        "": 3,
    }
    return sorted(
        rows,
        key=lambda row: (
            priority[row["role"]],
            row["speaker"].get_display_name().casefold(),
            row["speaker"].pk,
        ),
    )
