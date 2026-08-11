"""The ``go/{resource}/{opaque-id}`` resolver: one click, one redirect.

Implements the Link beat of the demo grammar (``docs/buzz-demo-map.md``) and
the product standard (``docs/product-standard-buzz-workflows.md``): a durable,
permission-aware link that resolves server-side, authorizes before it
redirects, and never exposes a command route as a link.

The opaque identifier encodes the target route's declared kwargs in order,
joined by ``~``. Event-scoped resources use ``{event}`` or
``{event}~{code|pk|kind|assignment}``; organiser-scoped resources use
``{organiser}``. Authorization mirrors the role matrix in
``tests/test_buzz_resource_registry.py``: intended audiences get a redirect,
everyone else gets a non-disclosing 404, and a GET can never mutate state.
"""

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import View
from django_scopes import scope
from pretalx.event.models import Event, Organiser

from .auth import can_manage, can_review, is_speaker
from .canonical_links import COMMAND, RESOURCES

RESOURCE_SEP = "~"

INT_KWARGS = ("pk", "assignment")


def by_resource(resource):
    for link in RESOURCES:
        if link.resource == resource:
            return link
    return None


def _split_opaque_id(link, opaque_id):
    parts = opaque_id.split(RESOURCE_SEP)
    if len(parts) != len(link.url_kwargs):
        raise Http404
    return dict(zip(link.url_kwargs, parts, strict=True))


def _reverse_target(link, parts):
    kwargs = {}
    for name, value in parts.items():
        if name in INT_KWARGS:
            try:
                kwargs[name] = int(value)
            except ValueError:
                raise Http404 from None
        else:
            kwargs[name] = value
    return reverse(f"plugins:speakerops:{link.route_name}", kwargs=kwargs)


def _authorized(request, link, parts):
    user = request.user
    if link.audience == "public":
        return True
    if not user.is_authenticated:
        return False
    if "event" in parts:
        event = Event.objects.filter(slug=parts["event"]).first()
        if event is None:
            raise Http404
        with scope(event=event):
            if link.audience == "speaker":
                return is_speaker(user, event)
            if link.audience == "reviewer":
                return can_review(user, event)
            if link.audience == "organiser":
                return can_manage(user, event)
        return False
    if "organiser" in parts:
        organiser = Organiser.objects.filter(slug=parts["organiser"]).first()
        if organiser is None:
            raise Http404
        return any(
            can_manage(user, item)
            for item in Event.objects.filter(organiser=organiser).order_by("date_from", "pk")
        )
    return False


class GoResolveView(View):
    """Resolve a durable workflow link to the exact view, or fail closed."""

    def get(self, request, resource, opaque_id):
        link = by_resource(resource)
        if link is None or link.interaction == COMMAND:
            raise Http404
        parts = _split_opaque_id(link, opaque_id)
        if not _authorized(request, link, parts):
            raise Http404
        return redirect(_reverse_target(link, parts))
