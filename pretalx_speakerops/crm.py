import csv
import io

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView
from django_scopes import scope
from pretalx.event.models import Event, Organiser
from pretalx.person.models import SpeakerProfile, User

from .auth import can_manage
from .models import (
    CRMContact,
    CRMEventLink,
    CRMOutreachLog,
    CRMPipelineCard,
    CRMPipelineHistory,
    CRMSegment,
)
from .views import EventContextMixin

MAX_CRM_IMPORT_ROWS = 1000
CRM_IMPORT_FIELDS = (
    "name",
    "email",
    "company",
    "job_title",
    "headshot_url",
    "biography",
    "tags",
)
HEADER_ALIASES = {
    "name": ("name", "full_name", "speaker", "speaker_name"),
    "email": ("email", "email_address"),
    "company": ("company", "organization", "organisation", "employer"),
    "job_title": ("job_title", "title", "role"),
    "headshot_url": ("headshot_url", "photo_url", "avatar_url", "headshot"),
    "biography": ("biography", "bio"),
    "tags": ("tags", "labels"),
}


def _normalise_header(value):
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _mapped_value(row, field, explicit):
    if explicit and explicit in row:
        return row[explicit].strip()
    normalised = {_normalise_header(key): value for key, value in row.items() if key}
    for alias in HEADER_ALIASES[field]:
        if alias in normalised:
            return (normalised[alias] or "").strip()
    return ""


def _tag_list(value):
    return sorted({item.strip() for item in value.replace(";", ",").split(",") if item.strip()})


def _render_message(template, contact, event):
    values = {
        "name": contact.name,
        "email": contact.email,
        "company": contact.company,
        "job_title": contact.job_title,
        "event": str(event.name),
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value).replace("{{" + key + "}}", value)
    return rendered


class CRMDirectoryView(EventContextMixin, TemplateView):
    """Organisation-wide CRM entered through an authorised event context."""

    permission = "manage"
    template_name = "pretalx_speakerops/crm_directory.html"

    @property
    def organiser(self):
        return self.event.organiser

    def dispatch(self, request, *args, **kwargs):
        if organiser_slug := kwargs.get("organiser"):
            organiser = get_object_or_404(Organiser, slug=organiser_slug)
            if not request.user.is_authenticated:
                return LoginRequiredMixin.dispatch(self, request, *args, **kwargs)
            events = Event.objects.filter(organiser=organiser).order_by("date_from", "pk")
            self.event = next((item for item in events if can_manage(request.user, item)), None)
            if not self.event:
                raise Http404
            with scope(event=self.event):
                response = LoginRequiredMixin.dispatch(self, request, *args, **kwargs)
                if hasattr(response, "render"):
                    response.render()
                return response
        return super().dispatch(request, *args, **kwargs)

    def _url(self):
        if "organiser" in self.kwargs:
            return reverse(
                "plugins:speakerops:speakerops_crm_org",
                kwargs={"organiser": self.organiser.slug},
            )
        return reverse("plugins:speakerops:speakerops_crm", kwargs={"event": self.event.slug})

    def _redirect(self):
        return redirect(self._url())

    def _contacts(self):
        contacts = CRMContact.objects.filter(organiser=self.organiser, merged_into__isnull=True)
        query = self.request.GET.get("q", "").strip()
        company = self.request.GET.get("company", "").strip()
        job_title = self.request.GET.get("job_title", "").strip()
        tag = self.request.GET.get("tag", "").strip()
        stage = self.request.GET.get("stage", "").strip()
        segment_id = self.request.GET.get("segment", "").strip()
        if query:
            contacts = contacts.filter(
                Q(name__icontains=query)
                | Q(email__icontains=query)
                | Q(company__icontains=query)
                | Q(job_title__icontains=query)
            )
        if company:
            contacts = contacts.filter(company__iexact=company)
        if job_title:
            contacts = contacts.filter(job_title__iexact=job_title)
        if tag:
            contacts = contacts.filter(tags__icontains=tag)
        if stage:
            contacts = contacts.filter(pipeline_card__stage=stage)
        if segment_id:
            contacts = contacts.filter(segments__pk=segment_id, segments__organiser=self.organiser)
        return contacts.distinct().select_related("source_speaker", "pipeline_card")

    def post(self, request, *args, **kwargs):
        """Handle both event-nested and canonical organisation CRM routes."""

        action = request.POST.get("action", "")
        handlers = {
            "save_contact": self._save_contact,
            "import_csv": self._import_csv,
            "merge": self._merge,
            "save_segment": self._save_segment,
            "move_stage": self._move_stage,
            "add_to_event": self._add_to_event,
            "log_outreach": self._log_outreach,
        }
        handler = handlers.get(action)
        if not handler:
            messages.error(request, "Choose a supported CRM action.")
            return self._redirect()
        return handler(request)

    def _owned_contact(self, value):
        return CRMContact.objects.filter(
            organiser=self.organiser, pk=value, merged_into__isnull=True
        ).first()

    def _save_contact(self, request):
        contact = self._owned_contact(request.POST.get("contact_id"))
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        if not name:
            messages.error(request, "Contact name is required.")
            return self._redirect()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Enter a valid contact email address.")
                return self._redirect()
        duplicate_query = Q(name__iexact=name)
        if email:
            duplicate_query |= Q(email__iexact=email)
        duplicate = (
            CRMContact.objects.filter(organiser=self.organiser, merged_into__isnull=True)
            .filter(duplicate_query)
            .exclude(pk=contact.pk if contact else None)
            .first()
            if email
            else None
        )
        values = {
            "name": name,
            "email": email,
            "company": request.POST.get("company", "").strip(),
            "job_title": request.POST.get("job_title", "").strip(),
            "headshot_url": request.POST.get("headshot_url", "").strip(),
            "biography": request.POST.get("biography", "").strip(),
            "tags": _tag_list(request.POST.get("tags", "")),
            "internal_notes": request.POST.get("internal_notes", "").strip(),
        }
        if contact:
            for key, value in values.items():
                setattr(contact, key, value)
            contact.save()
        else:
            contact = CRMContact.objects.create(organiser=self.organiser, **values)
            CRMPipelineCard.objects.create(organiser=self.organiser, contact=contact)
        if duplicate:
            messages.warning(
                request,
                f"Possible duplicate: {duplicate.name} has the same email. "
                "Compare and merge explicitly.",
            )
        messages.success(request, f"Saved CRM contact {contact.name}.")
        return self._redirect()

    def _import_csv(self, request):
        upload = request.FILES.get("csv_file")
        if not upload:
            messages.error(request, "Choose a CSV file to import.")
            return self._redirect()
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, "The CSV must be UTF-8 encoded.")
            return self._redirect()
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            messages.error(request, "The CSV needs a header row.")
            return self._redirect()
        explicit = {
            field: request.POST.get(f"map_{field}", "").strip() for field in CRM_IMPORT_FIELDS
        }
        rows = list(reader)
        if len(rows) > MAX_CRM_IMPORT_ROWS:
            messages.error(request, f"Import at most {MAX_CRM_IMPORT_ROWS} contacts at a time.")
            return self._redirect()
        parsed = []
        errors = []
        for number, row in enumerate(rows, 2):
            values = {
                field: _mapped_value(row, field, explicit[field]) for field in CRM_IMPORT_FIELDS
            }
            values["email"] = values["email"].lower()
            values["tags"] = _tag_list(values["tags"])
            if not values["name"]:
                errors.append(f"Row {number}: name is required.")
            if values["email"]:
                try:
                    validate_email(values["email"])
                except ValidationError:
                    errors.append(f"Row {number}: invalid email {values['email']}.")
            parsed.append(values)
        if errors:
            for error in errors[:12]:
                messages.error(request, error)
            return self._redirect()
        duplicate_count = 0
        with transaction.atomic():
            for values in parsed:
                duplicate_query = Q(name__iexact=values["name"])
                if values["email"]:
                    duplicate_query |= Q(email__iexact=values["email"])
                if (
                    CRMContact.objects.filter(
                        organiser=self.organiser,
                        merged_into__isnull=True,
                    )
                    .filter(duplicate_query)
                    .exists()
                ):
                    duplicate_count += 1
                contact = CRMContact.objects.create(organiser=self.organiser, **values)
                CRMPipelineCard.objects.create(organiser=self.organiser, contact=contact)
        messages.success(request, f"Imported {len(parsed)} CRM contacts.")
        if duplicate_count:
            messages.warning(
                request,
                f"Flagged {duplicate_count} possible "
                f"duplicate{'s' if duplicate_count != 1 else ''}; "
                "no records were merged automatically.",
            )
        return self._redirect()

    def _merge(self, request):
        primary = self._owned_contact(request.POST.get("primary_id"))
        duplicate = self._owned_contact(request.POST.get("duplicate_id"))
        if not primary or not duplicate or primary.pk == duplicate.pk:
            messages.error(request, "Choose two different contacts from this organizer.")
            return self._redirect()
        with transaction.atomic():
            for field in (
                "email",
                "company",
                "job_title",
                "headshot_url",
                "biography",
                "internal_notes",
                "source_speaker",
            ):
                if not getattr(primary, field) and getattr(duplicate, field):
                    setattr(primary, field, getattr(duplicate, field))
            primary.tags = sorted(set(primary.tags) | set(duplicate.tags))
            primary.save()
            for segment in duplicate.segments.filter(organiser=self.organiser):
                segment.contacts.add(primary)
            CRMOutreachLog.objects.filter(organiser=self.organiser, contact=duplicate).update(
                contact=primary
            )
            for link in CRMEventLink.objects.filter(organiser=self.organiser, contact=duplicate):
                CRMEventLink.objects.get_or_create(
                    organiser=self.organiser,
                    contact=primary,
                    event=link.event,
                    defaults={"user": link.user, "added_by": request.user},
                )
            primary_card, _ = CRMPipelineCard.objects.get_or_create(
                organiser=self.organiser, contact=primary
            )
            duplicate_card = CRMPipelineCard.objects.filter(
                organiser=self.organiser, contact=duplicate
            ).first()
            if duplicate_card:
                CRMPipelineHistory.objects.filter(card=duplicate_card).update(card=primary_card)
                duplicate_card.delete()
            duplicate.merged_into = primary
            duplicate.save(update_fields=["merged_into"])
        messages.success(request, f"Merged {duplicate.name} into primary contact {primary.name}.")
        return self._redirect()

    def _save_segment(self, request):
        name = request.POST.get("segment_name", "").strip()
        selected = request.POST.getlist("contacts")
        if not name:
            messages.error(request, "Segment name is required.")
            return self._redirect()
        contacts = CRMContact.objects.filter(
            organiser=self.organiser, merged_into__isnull=True, pk__in=selected
        )
        criteria = {
            key: self.request.GET.get(key, "").strip()
            for key in ("q", "company", "job_title", "tag", "stage")
            if self.request.GET.get(key, "").strip()
        }
        segment, _ = CRMSegment.objects.update_or_create(
            organiser=self.organiser, name=name, defaults={"filter_definition": criteria}
        )
        segment.contacts.set(contacts)
        messages.success(request, f"Saved segment {name} with {contacts.count()} contacts.")
        return self._redirect()

    def _move_stage(self, request):
        contact = self._owned_contact(request.POST.get("contact_id"))
        stage = request.POST.get("stage", "")
        if not contact or stage not in dict(CRMPipelineCard.STAGE_CHOICES):
            messages.error(request, "Choose a valid contact and pipeline stage.")
            return self._redirect()
        card, _ = CRMPipelineCard.objects.get_or_create(organiser=self.organiser, contact=contact)
        prior = card.stage
        note = request.POST.get("note", "").strip()
        card.stage = stage
        if note:
            card.notes = note
        card.save()
        CRMPipelineHistory.objects.create(
            card=card, from_stage=prior, to_stage=stage, note=note, actor=request.user
        )
        messages.success(request, f"Moved {contact.name} from {prior} to {stage}.")
        return self._redirect()

    def _add_to_event(self, request):
        contact = self._owned_contact(request.POST.get("contact_id"))
        if not contact:
            messages.error(request, "Choose a valid CRM contact for event handoff.")
            return self._redirect()
        if not contact.email:
            messages.error(
                request,
                "Verify and save the contact email before event handoff. "
                "No contact data was inferred or invented.",
            )
            return self._redirect()
        target_event = Event.objects.filter(
            organiser=self.organiser, pk=request.POST.get("target_event") or self.event.pk
        ).first()
        if not target_event:
            messages.error(request, "Choose an event owned by this organizer.")
            return self._redirect()
        with transaction.atomic(), scope(event=target_event):
            user = User.objects.filter(email__iexact=contact.email).first()
            if not user:
                user = User.objects.create_user(email=contact.email, name=contact.name)
                user.set_unusable_password()
                user.save(update_fields=["password"])
            profile, _ = SpeakerProfile.objects.get_or_create(event=target_event, user=user)
            if contact.biography and not profile.biography:
                profile.biography = contact.biography
                profile.save(update_fields=["biography"])
            CRMEventLink.objects.update_or_create(
                organiser=self.organiser,
                contact=contact,
                event=target_event,
                defaults={"user": user, "added_by": request.user, "added_at": timezone.now()},
            )
        messages.success(request, f"Added {contact.name} to {target_event.name} without re-keying.")
        return self._redirect()

    def _log_outreach(self, request):
        contacts = CRMContact.objects.filter(
            organiser=self.organiser,
            merged_into__isnull=True,
            pk__in=request.POST.getlist("contacts"),
        )
        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("body", "").strip()
        if not contacts or not subject or not body:
            messages.error(request, "Select contacts and provide an outreach subject and body.")
            return self._redirect()
        CRMOutreachLog.objects.bulk_create(
            [
                CRMOutreachLog(
                    organiser=self.organiser,
                    contact=contact,
                    event=self.event,
                    subject=_render_message(subject, contact, self.event),
                    rendered_body=_render_message(body, contact, self.event),
                    actor=request.user,
                )
                for contact in contacts
            ]
        )
        messages.success(request, f"Logged personalized outreach for {contacts.count()} contacts.")
        return self._redirect()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # URL kwargs may arrive in TemplateView's context as the raw slug. Keep
        # templates and the organiser base layout on the authoritative object.
        context["event"] = self.event
        contacts = self._contacts()
        all_contacts = CRMContact.objects.filter(organiser=self.organiser, merged_into__isnull=True)
        duplicate_names = list(
            all_contacts.values("name")
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .values_list("name", flat=True)
        )
        duplicate_emails = list(
            all_contacts.exclude(email="")
            .values("email")
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .values_list("email", flat=True)
        )
        duplicate_groups = []
        seen_groups = set()
        for queryset in (
            *(all_contacts.filter(name__iexact=name) for name in duplicate_names),
            *(all_contacts.filter(email__iexact=email) for email in duplicate_emails),
        ):
            group = list(queryset)
            key = tuple(sorted(contact.pk for contact in group))
            if key not in seen_groups:
                seen_groups.add(key)
                duplicate_groups.append(group)
        stage_counts = {
            item["stage"]: item["total"]
            for item in CRMPipelineCard.objects.filter(organiser=self.organiser)
            .values("stage")
            .annotate(total=Count("pk"))
        }
        pipeline_columns = [
            {
                "value": value,
                "label": label,
                "contacts": all_contacts.filter(pipeline_card__stage=value),
            }
            for value, label in CRMPipelineCard.STAGE_CHOICES
        ]
        top_companies = list(
            all_contacts.exclude(company="")
            .values("company")
            .annotate(total=Count("pk"))
            .order_by("-total", "company")[:8]
        )
        context.update(
            contacts=contacts,
            result_count=contacts.count(),
            total_contacts=all_contacts.count(),
            companies=all_contacts.exclude(company="")
            .values_list("company", flat=True)
            .distinct()
            .order_by("company"),
            job_titles=all_contacts.exclude(job_title="")
            .values_list("job_title", flat=True)
            .distinct()
            .order_by("job_title"),
            segments=CRMSegment.objects.filter(organiser=self.organiser).annotate(
                contact_count=Count("contacts")
            ),
            duplicate_groups=duplicate_groups,
            stage_choices=CRMPipelineCard.STAGE_CHOICES,
            stage_counts=stage_counts,
            pipeline_columns=pipeline_columns,
            top_companies=top_companies,
            organiser_events=Event.objects.filter(organiser=self.organiser).order_by(
                "-date_from", "name"
            ),
            linked_count=CRMEventLink.objects.filter(organiser=self.organiser).count(),
            outreach_count=CRMOutreachLog.objects.filter(organiser=self.organiser).count(),
            recent_outreach=CRMOutreachLog.objects.filter(organiser=self.organiser).select_related(
                "contact", "event", "actor"
            )[:12],
            filters={
                key: self.request.GET.get(key, "").strip()
                for key in ("q", "company", "job_title", "tag", "stage", "segment")
            },
            crm_import_fields=CRM_IMPORT_FIELDS,
        )
        return context
