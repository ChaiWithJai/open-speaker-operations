import csv
import io
from datetime import date

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import redirect
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView
from django_scopes import scope
from pretalx.person.models import SpeakerProfile, User

from .models import (
    OnboardingTask,
    SpeakerOperationsProfile,
    TaskDefinition,
)
from .views import EventContextMixin

IMPORT_SIGNING_SALT = "speakerops-speaker-import"
MAX_IMPORT_ROWS = 500
OPTIONAL_IMPORT_FIELDS = (
    "workflow_status",
    "travel_preferences",
    "dietary_requirements",
    "accessibility_requirements",
)


def _event_speakers(event):
    return (
        User.objects.filter(Q(profiles__event=event) | Q(submissions__event=event))
        .distinct()
        .order_by("name", "email")
    )


def _header_guess(headers, aliases):
    normalized = {header.strip().lower().replace(" ", "_"): header for header in headers}
    return next((normalized[item] for item in aliases if item in normalized), "")


class SpeakerOperationsView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/speaker_operations.html"

    def _redirect(self):
        return redirect(
            reverse(
                "plugins:speakerops:speakerops_speakers",
                kwargs={"event": self.event.slug},
            )
        )

    def post(self, request, event):
        action = request.POST.get("action")
        with scope(event=self.event):
            allowed = _event_speakers(self.event)
            if action == "update_speaker":
                speaker = allowed.filter(pk=request.POST.get("speaker_id")).first()
                if not speaker:
                    messages.error(request, "That speaker does not belong to this event.")
                    return self._redirect()
                status = request.POST.get("workflow_status", "")
                valid_statuses = {item[0] for item in SpeakerOperationsProfile.STATUS_CHOICES}
                if status not in valid_statuses:
                    messages.error(request, "Choose a valid workflow status.")
                    return self._redirect()
                profile, _ = SpeakerOperationsProfile.objects.get_or_create(
                    event=self.event, speaker=speaker
                )
                profile.workflow_status = status
                profile.travel_preferences = request.POST.get("travel_preferences", "").strip()
                profile.dietary_requirements = request.POST.get("dietary_requirements", "").strip()
                profile.accessibility_requirements = request.POST.get(
                    "accessibility_requirements", ""
                ).strip()
                profile.logistics_notes = request.POST.get("logistics_notes", "").strip()
                profile.save()
                messages.success(request, f"Updated workflow and logistics for {speaker.name}.")
                return self._redirect()

            if action == "create_task":
                speaker_ids = request.POST.getlist("speakers")
                speakers = list(allowed.filter(pk__in=speaker_ids))
                name = request.POST.get("name", "").strip()
                instructions = request.POST.get("instructions", "").strip()
                completion_criteria = request.POST.get("completion_criteria", "").strip()
                try:
                    due_date = date.fromisoformat(request.POST.get("due_date", ""))
                except ValueError:
                    due_date = None
                if not name or not instructions or not completion_criteria or not due_date:
                    messages.error(
                        request, "Name, instructions, done criteria, and due date are required."
                    )
                    return self._redirect()
                if not speakers or len(speakers) != len(set(speaker_ids)):
                    messages.error(request, "Select at least one speaker from this event.")
                    return self._redirect()
                base_slug = slugify(name)[:64] or "speaker-action"
                slug = base_slug
                suffix = 2
                while TaskDefinition.objects.filter(event=self.event, slug=slug).exists():
                    slug = f"{base_slug[:60]}-{suffix}"
                    suffix += 1
                position = (
                    TaskDefinition.objects.filter(event=self.event).aggregate(Max("position"))[
                        "position__max"
                    ]
                    or 0
                ) + 1
                with transaction.atomic():
                    definition = TaskDefinition.objects.create(
                        event=self.event,
                        position=position,
                        slug=slug,
                        name=name,
                        instructions=instructions,
                        completion_criteria=completion_criteria,
                        task_type="action",
                        completion_evaluator="acknowledgement",
                        due_days_after_acceptance=0,
                    )
                    OnboardingTask.objects.bulk_create(
                        [
                            OnboardingTask(
                                event=self.event,
                                speaker=speaker,
                                definition=definition,
                                accepted_at=timezone.now(),
                                due_date=due_date,
                            )
                            for speaker in speakers
                        ]
                    )
                messages.success(
                    request,
                    f"Assigned “{name}” to {len(speakers)} "
                    f"speaker{'s' if len(speakers) != 1 else ''}.",
                )
                return self._redirect()
        messages.error(request, "Choose a supported speaker operation.")
        return self._redirect()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get("status", "").strip()
        query = self.request.GET.get("q", "").strip()
        with scope(event=self.event):
            speakers = _event_speakers(self.event)
            if query:
                speakers = speakers.filter(Q(name__icontains=query) | Q(email__icontains=query))
            operation_profiles = {
                profile.speaker_id: profile
                for profile in SpeakerOperationsProfile.objects.filter(
                    event=self.event, speaker__in=speakers
                )
            }
            task_rows = OnboardingTask.objects.filter(event=self.event, speaker__in=speakers)
            task_counts = {}
            for speaker_id, status in task_rows.values_list("speaker_id", "status"):
                counts = task_counts.setdefault(speaker_id, {"total": 0, "resolved": 0})
                counts["total"] += 1
                if status in (OnboardingTask.COMPLETE, OnboardingTask.WAIVED):
                    counts["resolved"] += 1
            rows = []
            for speaker in speakers:
                profile = operation_profiles.get(speaker.pk)
                effective_status = (
                    profile.workflow_status if profile else SpeakerOperationsProfile.INVITED
                )
                if status_filter and effective_status != status_filter:
                    continue
                rows.append(
                    {
                        "speaker": speaker,
                        "profile": profile,
                        "workflow_status": effective_status,
                        "counts": task_counts.get(speaker.pk, {"total": 0, "resolved": 0}),
                    }
                )
        context.update(
            event=self.event,
            rows=rows,
            all_speakers=list(_event_speakers(self.event)),
            statuses=SpeakerOperationsProfile.STATUS_CHOICES,
            status_filter=status_filter,
            query=query,
            default_due_date=timezone.localdate(),
        )
        return context


class SpeakerImportView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/speaker_import.html"

    def _render_error(self, message):
        messages.error(self.request, message)
        return self.get(self.request, event=self.event.slug)

    def post(self, request, event):
        action = request.POST.get("action", "preview")
        if action == "preview":
            upload = request.FILES.get("csv_file")
            if not upload:
                return self._render_error("Choose a CSV file to preview.")
            if upload.size > 1_000_000:
                return self._render_error("CSV files must be 1 MB or smaller.")
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                return self._render_error("CSV must use UTF-8 text encoding.")
            reader = csv.DictReader(io.StringIO(text))
            headers = [header.strip() for header in (reader.fieldnames or []) if header.strip()]
            raw_rows = list(reader)
            if any(None in row for row in raw_rows):
                return self._render_error(
                    "A CSV row has more values than the header. Correct the file and retry."
                )
            rows = [
                {str(key).strip(): (value or "").strip() for key, value in row.items()}
                for row in raw_rows
            ]
            if not headers or not rows:
                return self._render_error("CSV must contain a header row and at least one speaker.")
            if len(rows) > MAX_IMPORT_ROWS:
                return self._render_error(f"Import at most {MAX_IMPORT_ROWS} speakers at a time.")
            payload = {"headers": headers, "rows": rows}
            token = signing.dumps(payload, salt=IMPORT_SIGNING_SALT, compress=True)
            guesses = {
                "name": _header_guess(headers, ("name", "full_name", "speaker_name")),
                "email": _header_guess(headers, ("email", "email_address")),
                "workflow_status": _header_guess(headers, ("workflow_status", "status")),
                "travel_preferences": _header_guess(headers, ("travel_preferences", "travel")),
                "dietary_requirements": _header_guess(headers, ("dietary_requirements", "dietary")),
                "accessibility_requirements": _header_guess(
                    headers, ("accessibility_requirements", "accessibility")
                ),
            }
            return self.render_to_response(
                self.get_context_data(
                    preview=True,
                    headers=headers,
                    rows=rows[:5],
                    row_count=len(rows),
                    token=token,
                    guesses=guesses,
                )
            )
        if action != "import":
            return self._render_error("Choose a supported import action.")
        try:
            payload = signing.loads(
                request.POST.get("token", ""), salt=IMPORT_SIGNING_SALT, max_age=3600
            )
        except signing.BadSignature:
            return self._render_error("That import preview expired. Upload the CSV again.")
        headers = payload["headers"]
        mapping = {
            field: request.POST.get(f"map_{field}", "")
            for field in ("name", "email", *OPTIONAL_IMPORT_FIELDS)
        }
        if not mapping["name"] or not mapping["email"]:
            return self._render_error("Map both the speaker name and email columns.")
        if any(value and value not in headers for value in mapping.values()):
            return self._render_error("One or more mapped columns are not in this CSV.")
        normalized = []
        errors = []
        seen = set()
        valid_statuses = {item[0] for item in SpeakerOperationsProfile.STATUS_CHOICES}
        for number, row in enumerate(payload["rows"], start=2):
            name = row.get(mapping["name"], "").strip()
            email = row.get(mapping["email"], "").strip().lower()
            try:
                validate_email(email)
            except ValidationError:
                errors.append(f"Row {number}: enter a valid email address.")
            if not name:
                errors.append(f"Row {number}: speaker name is required.")
            if email in seen:
                errors.append(f"Row {number}: duplicate email {email}.")
            seen.add(email)
            values = {
                field: row.get(mapping[field], "").strip() if mapping[field] else ""
                for field in OPTIONAL_IMPORT_FIELDS
            }
            if values["workflow_status"] and values["workflow_status"] not in valid_statuses:
                errors.append(
                    f"Row {number}: workflow status must be one of "
                    f"{', '.join(sorted(valid_statuses))}."
                )
            normalized.append({"name": name, "email": email, **values})
        if errors:
            for error in errors[:10]:
                messages.error(request, error)
            return self.get(request, event=event)
        created = updated = 0
        with scope(event=self.event), transaction.atomic():
            for row in normalized:
                speaker = User.objects.filter(email__iexact=row["email"]).first()
                if speaker:
                    updated += 1
                    if speaker.name != row["name"]:
                        speaker.name = row["name"]
                        speaker.save(update_fields=["name"])
                else:
                    speaker = User.objects.create_user(email=row["email"], name=row["name"])
                    speaker.set_unusable_password()
                    speaker.save(update_fields=["password"])
                    created += 1
                SpeakerProfile.objects.get_or_create(event=self.event, user=speaker)
                defaults = {
                    key: value
                    for key, value in row.items()
                    if key in OPTIONAL_IMPORT_FIELDS and value
                }
                SpeakerOperationsProfile.objects.update_or_create(
                    event=self.event, speaker=speaker, defaults=defaults
                )
        messages.success(
            request,
            f"Imported {len(normalized)} speakers: {created} created, "
            f"{updated} matched and updated.",
        )
        return redirect(
            reverse("plugins:speakerops:speakerops_speakers", kwargs={"event": self.event.slug})
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(event=self.event, optional_fields=OPTIONAL_IMPORT_FIELDS)
        return context
