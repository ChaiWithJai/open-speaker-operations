import io
from datetime import date
from pathlib import PurePath
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.generic import TemplateView, View
from django_scopes import scope
from PIL import Image, UnidentifiedImageError
from pretalx.person.models import SpeakerProfile, User
from pretalx.submission.models import Submission

from .models import (
    ContentRevision,
    EvidenceComment,
    OnboardingTask,
    SessionPublicationApproval,
    TaskDefinition,
    TaskEvidence,
)
from .views import EventContextMixin


def _content_url(event, fragment=""):
    return (
        reverse(
            "plugins:speakerops:speakerops_content_operations",
            kwargs={"event": event},
        )
        + fragment
    )


class ContentOperationsView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/content_operations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            evidence_queryset = (
                TaskEvidence.objects.select_related("reviewed_by")
                .prefetch_related("comments__author")
                .order_by("-version")
            )
            tasks = list(
                OnboardingTask.objects.filter(
                    event=self.event,
                    definition__completion_evaluator="upload",
                )
                .select_related("speaker", "definition", "submission")
                .prefetch_related(
                    Prefetch(
                        "evidence_items",
                        queryset=evidence_queryset,
                        to_attr="speakerops_evidence_items",
                    )
                )
                .distinct()
                .order_by("speaker__name", "definition__position", "pk")
            )
            selected_speaker = self.request.GET.get("speaker", "")
            selected_request = self.request.GET.get("request", "")
            selected_status = self.request.GET.get("status", "")
            for task in tasks:
                task.speakerops_latest_evidence = (
                    task.speakerops_evidence_items[0] if task.speakerops_evidence_items else None
                )
            if selected_speaker.isdigit():
                tasks = [task for task in tasks if task.speaker_id == int(selected_speaker)]
            if selected_request.isdigit():
                tasks = [task for task in tasks if task.definition_id == int(selected_request)]
            if selected_status == "missing":
                tasks = [task for task in tasks if task.speakerops_latest_evidence is None]
            elif selected_status in dict(TaskEvidence.REVIEW_STATUS_CHOICES):
                tasks = [
                    task
                    for task in tasks
                    if task.speakerops_latest_evidence
                    and task.speakerops_latest_evidence.review_status == selected_status
                ]
            speakers = list(
                User.objects.filter(submissions__event=self.event)
                .distinct()
                .order_by("name", "email")
            )
            file_requests = list(
                TaskDefinition.objects.filter(
                    event=self.event, completion_evaluator="upload"
                ).order_by("name")
            )
            submissions = list(
                Submission.objects.filter(event=self.event)
                .prefetch_related("speakers")
                .order_by("title")
            )
            approvals = {
                item.submission_id: item
                for item in SessionPublicationApproval.objects.filter(event=self.event)
            }
            publication_rows = [
                {
                    "submission": submission,
                    "approval": approvals.get(submission.pk),
                    "public": not approvals.get(submission.pk)
                    or approvals[submission.pk].status == SessionPublicationApproval.APPROVED,
                }
                for submission in submissions
            ]
            revisions = list(
                ContentRevision.objects.filter(event=self.event).select_related("actor")[:200]
            )
            for row in publication_rows:
                submission = row["submission"]
                submission.speakerops_revisions = [
                    revision
                    for revision in revisions
                    if revision.content_type == ContentRevision.SESSION
                    and revision.object_id == submission.pk
                ]
                for speaker in submission.speakers.all():
                    profile = SpeakerProfile.objects.filter(event=self.event, user=speaker).first()
                    speaker.speakerops_biography = profile.biography if profile else ""
                    speaker.speakerops_avatar_url = (
                        speaker.get_avatar_url(event=self.event, thumbnail="tiny") or ""
                    )
                    speaker.speakerops_revisions = [
                        revision
                        for revision in revisions
                        if revision.content_type == ContentRevision.SPEAKER
                        and revision.object_id == speaker.pk
                    ]
        context.update(
            event=self.event,
            rows=tasks,
            speakers=speakers,
            publication_rows=publication_rows,
            today=timezone.localdate(),
            selected_speaker=selected_speaker,
            selected_request=selected_request,
            selected_status=selected_status,
            file_requests=file_requests,
            review_statuses=TaskEvidence.REVIEW_STATUS_CHOICES,
        )
        return context


class CreateFileRequestView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event):
        name = request.POST.get("name", "").strip()
        instructions = request.POST.get("instructions", "").strip()
        criteria = request.POST.get("completion_criteria", "").strip()
        due_date = request.POST.get("due_date", "").strip()
        speaker_ids = request.POST.getlist("speakers")
        requested_extensions = {
            item.strip().lower().lstrip(".")
            for item in request.POST.get("extensions", "").split(",")
            if item.strip()
        }
        supported_extensions = requested_extensions & {"pdf", "pptx", "jpg", "jpeg", "png"}
        extensions = [f".{item}" for item in sorted(supported_extensions or {"pdf", "pptx"})]
        if not all((name, instructions, criteria, due_date, speaker_ids)):
            messages.error(
                request, "Name, instructions, file rules, due date, and speakers are required."
            )
            return redirect(_content_url(event, "#new-file-request"))
        try:
            due_date = date.fromisoformat(due_date)
        except ValueError:
            messages.error(request, "Choose a valid due date.")
            return redirect(_content_url(event, "#new-file-request"))
        with scope(event=self.event), transaction.atomic():
            speakers = list(
                User.objects.filter(
                    pk__in=speaker_ids,
                    submissions__event=self.event,
                ).distinct()
            )
            if len(speakers) != len(set(speaker_ids)):
                raise Http404
            base_slug = slugify(name)[:70] or "file-request"
            slug = base_slug
            suffix = 2
            while TaskDefinition.objects.filter(event=self.event, slug=slug).exists():
                slug = f"{base_slug[: 70 - len(str(suffix)) - 1]}-{suffix}"
                suffix += 1
            definition = TaskDefinition.objects.create(
                event=self.event,
                position=(TaskDefinition.objects.filter(event=self.event).count() + 1),
                slug=slug,
                name=name[:200],
                instructions=instructions,
                completion_criteria=criteria,
                task_type="file_request",
                completion_evaluator="upload",
                evaluator_config={"extensions": extensions, "max_size": 20_000_000},
            )
            created = 0
            for speaker in speakers:
                submission = (
                    Submission.objects.filter(event=self.event, speakers=speaker)
                    .order_by("pk")
                    .first()
                )
                OnboardingTask.objects.create(
                    event=self.event,
                    submission=submission,
                    speaker=speaker,
                    definition=definition,
                    due_date=due_date,
                )
                created += 1
        messages.success(request, f"Created “{name}” and assigned it to {created} speaker(s).")
        return redirect(_content_url(event, "#new-file-request"))


class EvidenceDownloadView(EventContextMixin, View):
    permission = "manage"

    def get(self, request, event, pk):
        with scope(event=self.event):
            evidence = get_object_or_404(TaskEvidence, pk=pk, event=self.event)
            if not evidence.upload:
                raise Http404
            evidence.upload.open("rb")
            return FileResponse(
                evidence.upload.file,
                as_attachment=True,
                filename=PurePath(evidence.upload.name).name,
                content_type=evidence.content_type or "application/octet-stream",
            )


class SpeakerEvidenceDownloadView(EventContextMixin, View):
    def get(self, request, event, pk):
        with scope(event=self.event):
            evidence = get_object_or_404(
                TaskEvidence.objects.select_related("task"),
                pk=pk,
                event=self.event,
                task__speaker=request.user,
            )
            if not evidence.upload:
                raise Http404
            evidence.upload.open("rb")
            return FileResponse(
                evidence.upload.file,
                as_attachment=True,
                filename=PurePath(evidence.upload.name).name,
                content_type=evidence.content_type or "application/octet-stream",
            )


def _create_comment(*, event, evidence, author, body):
    body = body.strip()
    if not body:
        return False
    EvidenceComment.objects.create(
        event=event,
        evidence=evidence,
        author=author,
        body=body,
    )
    return True


class OrganiserEvidenceCommentView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        with scope(event=self.event):
            evidence = get_object_or_404(TaskEvidence, pk=pk, event=self.event)
            created = _create_comment(
                event=self.event,
                evidence=evidence,
                author=request.user,
                body=request.POST.get("body", ""),
            )
        if not created:
            messages.error(request, "Write a comment before posting.")
        return redirect(_content_url(event, f"#evidence-{pk}"))


class SpeakerEvidenceCommentView(EventContextMixin, View):
    def post(self, request, event, pk):
        with scope(event=self.event):
            evidence = get_object_or_404(
                TaskEvidence.objects.select_related("task"),
                pk=pk,
                event=self.event,
                task__speaker=request.user,
            )
            created = _create_comment(
                event=self.event,
                evidence=evidence,
                author=request.user,
                body=request.POST.get("body", ""),
            )
        if not created:
            messages.error(request, "Write a comment before posting.")
        return redirect(
            reverse(
                "plugins:speakerops:speakerops_checklist",
                kwargs={"event": event},
            )
            + f"#evidence-{pk}"
        )


class LatestEvidenceZipView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event):
        task_ids = request.POST.getlist("tasks")
        with scope(event=self.event):
            tasks = list(
                OnboardingTask.objects.filter(
                    event=self.event,
                    pk__in=task_ids,
                    definition__completion_evaluator="upload",
                ).select_related("speaker", "definition", "submission")
            )
            latest = []
            for task in tasks:
                evidence = (
                    task.evidence_items.filter(upload__isnull=False).order_by("-version").first()
                )
                if evidence:
                    latest.append((task, evidence))
        if not latest:
            messages.error(request, "Select at least one uploaded deliverable.")
            return redirect(_content_url(event))
        payload = io.BytesIO()
        with ZipFile(payload, "w", compression=ZIP_DEFLATED) as archive:
            for task, evidence in latest:
                speaker = slugify(task.speaker.get_display_name()) or f"speaker-{task.speaker_id}"
                task_name = slugify(task.definition.name) or f"task-{task.pk}"
                filename = PurePath(evidence.upload.name).name
                evidence.upload.open("rb")
                archive.writestr(
                    f"{speaker}/{task_name}/v{evidence.version}-{evidence.pk}-{filename}",
                    evidence.upload.read(),
                )
        response = HttpResponse(payload.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = (
            f'attachment; filename="{slugify(self.event.slug)}-latest-deliverables.zip"'
        )
        response["X-SpeakerOps-File-Count"] = str(len(latest))
        return response


class SessionPublicationApprovalView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        status = request.POST.get("status", "")
        allowed = dict(SessionPublicationApproval.STATUS_CHOICES)
        if status not in allowed:
            raise Http404
        note = request.POST.get("note", "").strip()
        if status == SessionPublicationApproval.CHANGES_REQUESTED and not note:
            messages.error(request, "Explain the changes needed before blocking publication.")
            return redirect(_content_url(event, f"#session-{pk}"))
        with scope(event=self.event), transaction.atomic():
            submission = get_object_or_404(Submission, event=self.event, pk=pk)
            approval, _ = SessionPublicationApproval.objects.select_for_update().get_or_create(
                event=self.event,
                submission=submission,
            )
            approval.status = status
            approval.note = note
            approval.reviewed_at = timezone.now()
            approval.reviewed_by = request.user
            approval.save(update_fields=["status", "note", "reviewed_at", "reviewed_by", "updated"])
        messages.success(request, f"“{submission.title}” is now {allowed[status].lower()}.")
        return redirect(_content_url(event, f"#session-{pk}"))


class SessionContentEditView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        title = request.POST.get("title", "").strip()
        abstract = request.POST.get("abstract", "").strip()
        if not title:
            messages.error(request, "A session title is required.")
            return redirect(_content_url(event, f"#session-content-{pk}"))
        with scope(event=self.event), transaction.atomic():
            submission = get_object_or_404(
                Submission.objects.select_for_update(), event=self.event, pk=pk
            )
            ContentRevision.objects.create(
                event=self.event,
                content_type=ContentRevision.SESSION,
                object_id=submission.pk,
                label=submission.title,
                snapshot={"title": submission.title, "abstract": submission.abstract},
                actor=request.user,
            )
            submission.title = title
            submission.abstract = abstract
            submission.save(update_fields=["title", "abstract", "updated"])
        messages.success(request, "Session content saved; the prior version remains restorable.")
        return redirect(_content_url(event, f"#session-content-{pk}"))


class SpeakerContentEditView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        biography = request.POST.get("biography", "").strip()
        headshot = request.FILES.get("headshot")
        if headshot:
            if headshot.size > 5_000_000:
                messages.error(request, "Headshots must be no larger than 5 MB.")
                return redirect(_content_url(event, f"#speaker-content-{pk}"))
            try:
                image = Image.open(headshot)
                image.verify()
            except (UnidentifiedImageError, OSError):
                messages.error(request, "Choose a valid JPG or PNG headshot.")
                return redirect(_content_url(event, f"#speaker-content-{pk}"))
            if image.format not in {"JPEG", "PNG"}:
                messages.error(request, "Choose a JPG or PNG headshot.")
                return redirect(_content_url(event, f"#speaker-content-{pk}"))
            headshot.seek(0)
        with scope(event=self.event), transaction.atomic():
            speaker = get_object_or_404(
                User.objects.filter(submissions__event=self.event).distinct(), pk=pk
            )
            profile, _ = SpeakerProfile.objects.select_for_update().get_or_create(
                event=self.event, user=speaker
            )
            ContentRevision.objects.create(
                event=self.event,
                content_type=ContentRevision.SPEAKER,
                object_id=speaker.pk,
                label=speaker.get_display_name(),
                snapshot={"biography": profile.biography, "avatar": speaker.avatar.name},
                actor=request.user,
            )
            profile.biography = biography
            profile.save(update_fields=["biography", "updated"])
            if headshot:
                speaker.avatar.save(headshot.name, headshot, save=True)
        messages.success(request, "Speaker profile saved; the prior version remains restorable.")
        return redirect(_content_url(event, f"#speaker-content-{pk}"))


class ContentRevisionRestoreView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        with scope(event=self.event), transaction.atomic():
            revision = get_object_or_404(
                ContentRevision.objects.select_for_update(), event=self.event, pk=pk
            )
            if revision.content_type == ContentRevision.SESSION:
                item = get_object_or_404(
                    Submission.objects.select_for_update(),
                    event=self.event,
                    pk=revision.object_id,
                )
                ContentRevision.objects.create(
                    event=self.event,
                    content_type=ContentRevision.SESSION,
                    object_id=item.pk,
                    label=item.title,
                    snapshot={"title": item.title, "abstract": item.abstract},
                    actor=request.user,
                    restored_from=revision,
                )
                item.title = revision.snapshot.get("title", item.title)
                item.abstract = revision.snapshot.get("abstract", item.abstract)
                item.save(update_fields=["title", "abstract", "updated"])
                fragment = f"#session-content-{item.pk}"
            elif revision.content_type == ContentRevision.SPEAKER:
                speaker = get_object_or_404(User, pk=revision.object_id)
                profile, _ = SpeakerProfile.objects.select_for_update().get_or_create(
                    event=self.event, user=speaker
                )
                ContentRevision.objects.create(
                    event=self.event,
                    content_type=ContentRevision.SPEAKER,
                    object_id=speaker.pk,
                    label=speaker.get_display_name(),
                    snapshot={"biography": profile.biography, "avatar": speaker.avatar.name},
                    actor=request.user,
                    restored_from=revision,
                )
                profile.biography = revision.snapshot.get("biography", profile.biography)
                profile.save(update_fields=["biography", "updated"])
                prior_avatar = revision.snapshot.get("avatar")
                if prior_avatar is not None:
                    speaker.avatar.name = prior_avatar
                    speaker.save(update_fields=["avatar"])
                fragment = f"#speaker-content-{speaker.pk}"
            else:
                raise Http404
        messages.success(
            request, f"Restored the version from {revision.created_at:%Y-%m-%d %H:%M}."
        )
        return redirect(_content_url(event, fragment))
