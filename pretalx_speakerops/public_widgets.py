from collections import defaultdict
from urllib.parse import urlencode

from csp.decorators import csp_update
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import TemplateView, View
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import SpeakerProfile
from pretalx.schedule.ical import get_slots_ical
from pretalx.submission.models import Answer

from .auth import can_manage
from .demo_assets import DEMO_HEADSHOT_BY_EMAIL

PUBLIC_WIDGETS = {
    "sessions": "Sessions",
    "speakers": "Speakers",
    "agenda": "Agenda",
    "itinerary": "My itinerary",
    "gallery": "Speaker gallery",
}


def _public_program(event):
    """Build every public surface from the one released-schedule authority."""
    schedule = event.current_schedule
    if not schedule:
        raise Http404
    slots = list(
        schedule.talks.filter(is_visible=True, submission__isnull=False)
        .select_related(
            "submission",
            "submission__track",
            "submission__submission_type",
            "room",
        )
        .prefetch_related("submission__speakers")
        .order_by("start", "room__position", "pk")
    )
    speaker_ids = {speaker.pk for slot in slots for speaker in slot.submission.speakers.all()}
    profiles = {
        profile.user_id: profile
        for profile in SpeakerProfile.objects.filter(event=event, user_id__in=speaker_ids)
    }
    public_answers = defaultdict(dict)
    for answer in Answer.objects.filter(
        question__event=event,
        person_id__in=speaker_ids,
        question__is_public=True,
    ).select_related("question"):
        key = str(answer.question.question).strip().casefold()
        public_answers[answer.person_id][key] = answer.answer.strip()

    speaker_cards = {}
    days = {}
    tracks = {}
    rooms = {}
    formats = {}
    for slot in slots:
        slot.public_start = timezone.localtime(slot.start, event.tz)
        slot.public_end = timezone.localtime(slot.real_end, event.tz)
        day_key = slot.public_start.date().isoformat()
        days.setdefault(
            day_key,
            {"key": day_key, "label": slot.public_start.strftime("%A, %B %-d"), "slots": []},
        )["slots"].append(slot)
        if slot.submission.track:
            tracks[slot.submission.track_id] = slot.submission.track
        if slot.submission.submission_type:
            formats[slot.submission.submission_type_id] = slot.submission.submission_type
        if slot.room:
            rooms[slot.room_id] = slot.room
        for speaker in slot.submission.speakers.all():
            if speaker.pk not in speaker_cards:
                answers = public_answers[speaker.pk]
                profile = profiles.get(speaker.pk)
                avatar_url = speaker.get_avatar_url(event=event, thumbnail="tiny") or ""
                if not avatar_url and event.slug == "speakerops-demo":
                    if demo_headshot := DEMO_HEADSHOT_BY_EMAIL.get(speaker.email):
                        avatar_url = static(demo_headshot)
                speaker_cards[speaker.pk] = {
                    "speaker": speaker,
                    "profile": profile,
                    "biography": profile.biography if profile else "",
                    "avatar_url": avatar_url,
                    "job_title": next(
                        (
                            answers[key]
                            for key in ("job title", "title", "role")
                            if answers.get(key)
                        ),
                        "",
                    ),
                    "company": next(
                        (
                            answers[key]
                            for key in ("company", "organisation", "organization")
                            if answers.get(key)
                        ),
                        "",
                    ),
                    "slots": [],
                }
            speaker_cards[speaker.pk]["slots"].append(slot)

    speakers = sorted(
        speaker_cards.values(),
        key=lambda item: (
            item["speaker"].get_display_name().rsplit(" ", 1)[-1].casefold(),
            item["speaker"].get_display_name().casefold(),
        ),
    )
    for card in speakers:
        card["search_text"] = " ".join(
            (
                card["speaker"].get_display_name(),
                card["job_title"],
                card["company"],
                str(card["biography"] or ""),
                *(slot.submission.title for slot in card["slots"]),
            )
        ).casefold()
    for slot in slots:
        slot.public_speaker_cards = [
            speaker_cards[speaker.pk] for speaker in slot.submission.speakers.all()
        ]
    return {
        "event": event,
        "schedule": schedule,
        "slots": slots,
        "days": list(days.values()),
        "tracks": sorted(tracks.values(), key=lambda item: str(item.name)),
        "formats": sorted(formats.values(), key=lambda item: str(item.name)),
        "rooms": sorted(rooms.values(), key=lambda item: str(item.name)),
        "speaker_cards": speakers,
    }


def _filter_session_slots(slots, *, query="", track="", session_format="", room=""):
    """Apply the public Sessions filters on the server as a no-JS authority."""

    needle = query.strip().casefold()
    filtered = []
    for slot in slots:
        speakers = " ".join(
            speaker.get_display_name() for speaker in slot.submission.speakers.all()
        )
        haystack = f"{slot.submission.title} {speakers}".casefold()
        if needle and needle not in haystack:
            continue
        if track and str(slot.submission.track_id or "") != track:
            continue
        if session_format and str(slot.submission.submission_type_id or "") != session_format:
            continue
        if room and str(slot.room_id or "") != room:
            continue
        filtered.append(slot)
    return filtered


@method_decorator(xframe_options_exempt, name="dispatch")
@method_decorator(csp_update({"frame-ancestors": ["*"]}), name="dispatch")
class PublicWidgetView(TemplateView):
    template_name = "pretalx_speakerops/public_widget.html"

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        self.widget = kwargs["widget"]
        if self.widget not in PUBLIC_WIDGETS:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            context.update(_public_program(self.event))
        selected_day = self.request.GET.get("day", "")
        valid_days = {day["key"] for day in context["days"]}
        if selected_day not in valid_days:
            selected_day = context["days"][0]["key"] if context["days"] else ""
        selected_query = self.request.GET.get("q", "").strip()
        selected_track = self.request.GET.get("track", "")
        selected_format = self.request.GET.get("format", "")
        selected_room = self.request.GET.get("room", "")
        if self.widget == "sessions":
            context["slots"] = _filter_session_slots(
                context["slots"],
                query=selected_query,
                track=selected_track,
                session_format=selected_format,
                room=selected_room,
            )
        context.update(
            widget=self.widget,
            widget_label=PUBLIC_WIDGETS[self.widget],
            theme="dark" if self.request.GET.get("theme") == "dark" else "light",
            compact=self.request.GET.get("fields") == "compact",
            selected_day=selected_day,
            selected_query=selected_query,
            selected_track=selected_track,
            selected_format=selected_format,
            selected_room=selected_room,
        )
        return context


@method_decorator(xframe_options_exempt, name="dispatch")
@method_decorator(csp_update({"frame-ancestors": ["*"]}), name="dispatch")
class PublicSpeakerDetailView(TemplateView):
    template_name = "pretalx_speakerops/public_speaker_detail.html"

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            program = _public_program(self.event)
            card = next(
                (
                    item
                    for item in program["speaker_cards"]
                    if item["speaker"].code == self.kwargs["code"]
                ),
                None,
            )
            if not card:
                raise Http404
        origin = self.request.GET.get("from", "")
        if origin not in {"gallery", "speakers"}:
            origin = "speakers"
        return_query = self.request.GET.get("q", "").strip()
        return_url = reverse(
            "plugins:speakerops:speakerops_public_widget",
            kwargs={"event": self.event.slug, "widget": origin},
        )
        if return_query:
            return_url = f"{return_url}?{urlencode({'q': return_query})}"
        return_url = f"{return_url}#speaker-{card['speaker'].code}"
        context.update(
            event=self.event,
            card=card,
            origin=origin,
            origin_label=PUBLIC_WIDGETS[origin],
            return_query=return_query,
            return_url=return_url,
        )
        return context


@method_decorator(xframe_options_exempt, name="dispatch")
@method_decorator(csp_update({"frame-ancestors": ["*"]}), name="dispatch")
class PublicSessionDetailView(TemplateView):
    template_name = "pretalx_speakerops/public_session_detail.html"

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            program = _public_program(self.event)
            slot = next(
                (item for item in program["slots"] if item.submission.code == self.kwargs["code"]),
                None,
            )
            if not slot:
                raise Http404
        origin = self.request.GET.get("from", "")
        if origin not in PUBLIC_WIDGETS:
            origin = "sessions"
        return_params = {
            key: self.request.GET[key]
            for key in ("day", "q", "track", "format", "room")
            if self.request.GET.get(key)
        }
        return_url = reverse(
            "plugins:speakerops:speakerops_public_widget",
            kwargs={"event": self.event.slug, "widget": origin},
        )
        if return_params:
            return_url = f"{return_url}?{urlencode(return_params)}"
        return_url = f"{return_url}#session-{slot.submission.code}"
        context.update(
            event=self.event,
            slot=slot,
            origin=origin,
            origin_label=PUBLIC_WIDGETS[origin],
            return_url=return_url,
        )
        return context


class SelectedScheduleIcsView(View):
    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        codes = {code for code in request.GET.get("sessions", "").split(",") if code}
        if not codes:
            raise Http404
        with scope(event=event):
            schedule = event.current_schedule
            if not schedule:
                raise Http404
            slots = list(
                schedule.talks.filter(
                    is_visible=True,
                    submission__isnull=False,
                    submission__code__in=codes,
                )
                .select_related("submission", "room")
                .order_by("start", "room__position", "pk")
            )
            if not slots:
                raise Http404
            calendar = get_slots_ical(event, slots, prodid_suffix="speakerops//personal")
        response = HttpResponse(calendar.serialize(), content_type="text/calendar")
        response["Content-Disposition"] = f'attachment; filename="{event.slug}-my-schedule.ics"'
        return response


class EmbedBuilderView(TemplateView):
    template_name = "pretalx_speakerops/embed_builder.html"

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        if not request.user.is_authenticated or not can_manage(request.user, self.event):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            context.update(_public_program(self.event))
        context.update(event=self.event, widgets=PUBLIC_WIDGETS)
        return context
