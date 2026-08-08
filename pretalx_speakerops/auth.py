from django.http import Http404


def require_event_permission(user, event, *permissions):
    if user.is_administrator:
        return
    if not any(user.has_perm(permission, event) for permission in permissions):
        raise Http404


def is_speaker(user, event):
    return event.submissions.filter(speakers=user).exists()
