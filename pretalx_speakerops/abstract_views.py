import csv
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView
from django_scopes import scope
from pretalx.mail.models import QueuedMail
from pretalx.person.models import User
from pretalx.submission.models import Submission, SubmissionStates

from .models import (
    EvaluationAnswer,
    EvaluationCriterion,
    EvaluationRound,
    OutboxEvent,
    RoundReviewAssignment,
    RoundReviewer,
)
from .presenter_roles import presenter_rows
from .views import EventContextMixin

SCORECARD_PRESETS = {
    "initial": (
        ("Originality", EvaluationCriterion.NUMERIC, 2, 1, 5, []),
        ("Relevance", EvaluationCriterion.NUMERIC, 1, 1, 5, []),
        (
            "Recommendation",
            EvaluationCriterion.DROPDOWN,
            0,
            None,
            None,
            ["Accept", "Maybe", "Reject"],
        ),
        ("Comments", EvaluationCriterion.TEXT, 0, None, None, []),
    ),
    "final": (
        ("Final Score", EvaluationCriterion.NUMERIC, 1, 1, 10, []),
        ("Comments", EvaluationCriterion.TEXT, 0, None, None, []),
    ),
}

REVIEWABLE_STATES = (
    SubmissionStates.SUBMITTED,
    SubmissionStates.ACCEPTED,
    SubmissionStates.REJECTED,
    SubmissionStates.CONFIRMED,
)


def _reviewable_submissions(event):
    """Committee review excludes drafts/withdrawals but survives a program decision."""
    return Submission.objects.filter(event=event, state__in=REVIEWABLE_STATES)


def _reviewers(event):
    return (
        User.objects.filter(
            Q(teams__all_events=True, teams__organiser=event.organiser)
            | Q(teams__limit_events=event),
            teams__is_reviewer=True,
        )
        .distinct()
        .order_by("name", "email")
    )


def _round_score(assignment):
    weighted = []
    for answer in assignment.answers.select_related("criterion"):
        criterion = answer.criterion
        if criterion.field_type != EvaluationCriterion.NUMERIC or answer.numeric_value is None:
            continue
        if criterion.weight > 0:
            weighted.append((answer.numeric_value, criterion.weight))
    weight = sum((item[1] for item in weighted), Decimal("0"))
    if not weight:
        return None
    return sum((value * item_weight for value, item_weight in weighted), Decimal("0")) / weight


class AbstractManagementView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/abstract_management.html"

    def _round(self, round_id):
        return get_object_or_404(EvaluationRound, event=self.event, pk=round_id)

    def _redirect(self, anchor=""):
        url = reverse(
            "plugins:speakerops:speakerops_abstract_management",
            kwargs={"event": self.event.slug},
        )
        return redirect(f"{url}{anchor}")

    @transaction.atomic
    def post(self, request, event):
        with scope(event=self.event):
            action = request.POST.get("action")
            if action == "create_round":
                self._create_round(request)
                return self._redirect("#evaluation-rounds")
            if action in {"assign_selected", "assign_exact", "auto_assign"}:
                self._assign(
                    request,
                    auto=action == "auto_assign",
                    replace=action == "assign_exact",
                )
                return self._redirect("#assignments")
            if action == "send_reminders":
                self._send_reminders(request)
                return self._redirect("#progress")
        raise Http404

    def _create_round(self, request):
        name = request.POST.get("name", "").strip()
        opens_at = request.POST.get("opens_at", "")
        closes_at = request.POST.get("closes_at", "")
        preset = request.POST.get("scorecard_preset", "")
        if not name or not opens_at or not closes_at or preset not in SCORECARD_PRESETS:
            messages.error(request, "Name, dates, and a scorecard are required.")
            return
        if opens_at > closes_at:
            messages.error(request, "The round must close on or after its opening date.")
            return
        round_obj, created = EvaluationRound.objects.get_or_create(
            event=self.event,
            name=name,
            defaults={
                "position": EvaluationRound.objects.filter(event=self.event).count(),
                "opens_at": opens_at,
                "closes_at": closes_at,
                "blinded": request.POST.get("blinded") == "yes",
            },
        )
        if not created and round_obj.assignments.exists():
            messages.error(
                request,
                "This round already has assignments. Its dates, blind policy, and scorecard are "
                "locked so submitted evaluations keep their original meaning.",
            )
            return
        if not created:
            round_obj.opens_at = opens_at
            round_obj.closes_at = closes_at
            round_obj.blinded = request.POST.get("blinded") == "yes"
            round_obj.save(update_fields=["opens_at", "closes_at", "blinded", "updated"])
        round_obj.criteria.all().delete()
        EvaluationCriterion.objects.bulk_create(
            [
                EvaluationCriterion(
                    event=self.event,
                    round=round_obj,
                    position=position,
                    name=criterion[0],
                    field_type=criterion[1],
                    weight=criterion[2],
                    minimum=criterion[3],
                    maximum=criterion[4],
                    options=criterion[5],
                )
                for position, criterion in enumerate(SCORECARD_PRESETS[preset])
            ]
        )
        messages.success(request, f"{round_obj.name} {'created' if created else 'updated'}.")

    def _assign(self, request, *, auto, replace=False):
        round_obj = self._round(request.POST.get("round_id"))
        reviewer = get_object_or_404(_reviewers(self.event), pk=request.POST.get("reviewer_id"))
        try:
            assignment_limit = max(1, min(500, int(request.POST.get("assignment_limit", 5))))
        except (TypeError, ValueError):
            assignment_limit = 5
        membership, _ = RoundReviewer.objects.update_or_create(
            event=self.event,
            round=round_obj,
            reviewer=reviewer,
            defaults={"assignment_limit": assignment_limit},
        )
        submissions = _reviewable_submissions(self.event)
        if auto:
            track_id = request.POST.get("track_id")
            if track_id:
                submissions = submissions.filter(track_id=track_id)
            already = round_obj.assignments.filter(reviewer=reviewer).count()
            submissions = submissions.exclude(
                speakerops_round_assignments__round=round_obj,
                speakerops_round_assignments__reviewer=reviewer,
            ).order_by("title")[: max(0, membership.assignment_limit - already)]
        else:
            selected = request.POST.getlist("submissions")
            selected_queryset = submissions.filter(pk__in=selected).order_by("title")[
                : membership.assignment_limit
            ]
            selected_ids = list(selected_queryset.values_list("pk", flat=True))
            if replace:
                round_obj.assignments.filter(reviewer=reviewer).exclude(
                    submission_id__in=selected_ids
                ).delete()
            already = round_obj.assignments.filter(reviewer=reviewer).count()
            submissions = (
                submissions.filter(pk__in=selected_ids)
                .exclude(
                    speakerops_round_assignments__round=round_obj,
                    speakerops_round_assignments__reviewer=reviewer,
                )
                .order_by("title")[: max(0, membership.assignment_limit - already)]
            )
        created = 0
        for submission in submissions:
            _assignment, was_created = RoundReviewAssignment.objects.get_or_create(
                event=self.event,
                round=round_obj,
                reviewer=reviewer,
                submission=submission,
            )
            created += int(was_created)
        messages.success(
            request,
            f"{created} assignment{'s' if created != 1 else ''} added to {round_obj.name}; "
            f"reviewer cap is {membership.assignment_limit}"
            f"{' and the queue now exactly matches the selection' if replace else ''}.",
        )

    def _send_reminders(self, request):
        memberships = RoundReviewer.objects.filter(
            event=self.event, pk__in=request.POST.getlist("memberships")
        ).select_related("round", "reviewer")
        sent = 0
        for membership in memberships:
            pending = membership.round.assignments.filter(
                reviewer=membership.reviewer, status=RoundReviewAssignment.ASSIGNED
            ).count()
            if not pending:
                continue
            membership.last_reminded_at = timezone.now()
            membership.save(update_fields=["last_reminded_at", "updated"])
            review_url = request.build_absolute_uri(
                reverse(
                    "plugins:speakerops:speakerops_round_review_queue",
                    kwargs={"event": self.event.slug},
                )
            )
            queued_mail = QueuedMail.objects.create(
                event=self.event,
                subject=f"Review assignments waiting: {self.event.name}",
                text=(
                    f"You have {pending} outstanding review assignment(s) in "
                    f"{membership.round.name}. Open {review_url} to continue."
                ),
            )
            queued_mail.to_users.add(membership.reviewer)
            queued_mail.send(requestor=request.user)
            OutboxEvent.objects.create(
                event=self.event,
                kind="review.reminder",
                aggregate_type="round_reviewer",
                aggregate_id=membership.pk,
                payload={
                    "reviewer": membership.reviewer.email,
                    "round": membership.round.name,
                    "pending": pending,
                    "queued_mail_id": queued_mail.pk,
                },
            )
            sent += 1
        messages.success(request, f"Reminder queued for {sent} lagging reviewer(s).")

    def _results(self, rounds):
        result = []
        for round_obj in rounds:
            rows = []
            assignments = (
                round_obj.assignments.exclude(status=RoundReviewAssignment.RECUSED)
                .select_related("submission", "reviewer")
                .prefetch_related(
                    "answers__criterion",
                    "submission__speakers",
                    "submission__speakerops_presenter_roles__speaker",
                )
            )
            grouped = {}
            for assignment in assignments:
                grouped.setdefault(assignment.submission_id, []).append(assignment)
            for _submission_id, reviews in grouped.items():
                completed_reviews = [
                    review for review in reviews if review.status == RoundReviewAssignment.COMPLETE
                ]
                scores = [
                    score
                    for review in completed_reviews
                    if (score := _round_score(review)) is not None
                ]
                aggregate = sum(scores, Decimal("0")) / len(scores) if scores else None
                evidence = []
                for review in reviews:
                    answers = []
                    for answer in review.answers.all():
                        value = (
                            answer.numeric_value
                            if answer.numeric_value is not None
                            else answer.choice_value or answer.text_value
                        )
                        answers.append({"criterion": answer.criterion, "value": value})
                    answers.sort(
                        key=lambda item: (item["criterion"].position, item["criterion"].pk)
                    )
                    evidence.append({"assignment": review, "answers": answers})
                rows.append(
                    {
                        "submission": reviews[0].submission,
                        "aggregate": aggregate,
                        "review_count": len(completed_reviews),
                        "assignments": reviews,
                        "evidence": evidence,
                        "presenters": presenter_rows(reviews[0].submission),
                    }
                )
            descending = self.request.GET.get("sort", "desc") != "asc"
            rows.sort(
                key=lambda row: (
                    row["aggregate"] is None,
                    -(row["aggregate"] or Decimal("0"))
                    if descending
                    else row["aggregate"] or Decimal("0"),
                    row["submission"].title.casefold(),
                )
            )
            result.append((round_obj, rows))
        return result

    def get(self, request, *args, **kwargs):
        with scope(event=self.event):
            rounds = list(
                EvaluationRound.objects.filter(event=self.event).prefetch_related(
                    "criteria",
                    Prefetch(
                        "reviewer_memberships",
                        queryset=RoundReviewer.objects.select_related("reviewer"),
                    ),
                )
            )
            if request.GET.get("export") == "csv":
                return self._export(rounds)
        return super().get(request, *args, **kwargs)

    def _export(self, rounds):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{self.event.slug}-round-review-results.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "round",
                "code",
                "title",
                "weighted_average",
                "review_count",
                "reviewer",
                "assignment_status",
                "criterion_scores",
            ]
        )
        for round_obj, rows in self._results(rounds):
            for row in rows:
                for assignment in row["assignments"]:
                    scores = {}
                    for answer in assignment.answers.select_related("criterion").order_by(
                        "criterion__position", "criterion__pk"
                    ):
                        scores[answer.criterion.name] = (
                            str(answer.numeric_value)
                            if answer.numeric_value is not None
                            else answer.choice_value or answer.text_value
                        )
                    writer.writerow(
                        [
                            round_obj.name,
                            row["submission"].code,
                            row["submission"].title,
                            row["aggregate"],
                            row["review_count"],
                            assignment.reviewer.email,
                            assignment.status,
                            json.dumps(scores, ensure_ascii=False, sort_keys=True),
                        ]
                    )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            rounds = list(
                EvaluationRound.objects.filter(event=self.event).prefetch_related(
                    "criteria",
                    Prefetch(
                        "reviewer_memberships",
                        queryset=RoundReviewer.objects.select_related("reviewer").prefetch_related(
                            "round__assignments"
                        ),
                    ),
                    Prefetch(
                        "assignments",
                        queryset=RoundReviewAssignment.objects.select_related(
                            "reviewer", "submission"
                        ),
                    ),
                )
            )
            progress = []
            for round_obj in rounds:
                for membership in round_obj.reviewer_memberships.all():
                    assigned = sum(
                        assignment.reviewer_id == membership.reviewer_id
                        and assignment.status != RoundReviewAssignment.RECUSED
                        for assignment in round_obj.assignments.all()
                    )
                    completed = sum(
                        assignment.reviewer_id == membership.reviewer_id
                        and assignment.status == RoundReviewAssignment.COMPLETE
                        for assignment in round_obj.assignments.all()
                    )
                    progress.append(
                        {
                            "membership": membership,
                            "assigned": assigned,
                            "completed": completed,
                            "percent": round(completed * 100 / assigned) if assigned else 0,
                        }
                    )
            context.update(
                event=self.event,
                rounds=rounds,
                reviewers=_reviewers(self.event),
                submissions=_reviewable_submissions(self.event)
                .select_related("track")
                .order_by("title"),
                tracks=self.event.tracks.all().order_by("position", "name"),
                progress=progress,
                round_results=self._results(rounds),
            )
        return context


class RoundReviewView(EventContextMixin, TemplateView):
    permission = "review"
    template_name = "pretalx_speakerops/round_review.html"

    def _assignments(self):
        assignments = (
            RoundReviewAssignment.objects.filter(
                event=self.event,
                reviewer=self.request.user,
            )
            .exclude(status=RoundReviewAssignment.RECUSED)
            .select_related("round", "submission", "submission__track")
        )
        return assignments.order_by("round__position", "submission__title")

    def _assignment(self):
        assignments = self._assignments()
        if assignment_id := self.kwargs.get("assignment"):
            return get_object_or_404(assignments, pk=assignment_id)
        return assignments.first()

    @transaction.atomic
    def post(self, request, event, assignment=None):
        with scope(event=self.event):
            assignment_obj = self._assignment()
            if not assignment_obj:
                raise Http404
            if request.POST.get("action") == "recuse":
                assignment_obj.status = RoundReviewAssignment.RECUSED
                assignment_obj.recusal_reason = request.POST.get("recusal_reason", "").strip()
                assignment_obj.submitted_at = timezone.now()
                assignment_obj.save(
                    update_fields=["status", "recusal_reason", "submitted_at", "updated"]
                )
                messages.success(
                    request, "Conflict declared. This proposal left your actionable queue."
                )
                return redirect(
                    reverse(
                        "plugins:speakerops:speakerops_round_review_queue",
                        kwargs={"event": self.event.slug},
                    )
                )
            for criterion in assignment_obj.round.criteria.all():
                raw_value = request.POST.get(f"criterion_{criterion.pk}", "").strip()
                if criterion.required and not raw_value:
                    messages.error(request, f"{criterion.name} is required.")
                    return redirect(request.path)
                answer, _ = EvaluationAnswer.objects.get_or_create(
                    event=self.event, assignment=assignment_obj, criterion=criterion
                )
                if criterion.field_type == EvaluationCriterion.NUMERIC:
                    try:
                        numeric = Decimal(raw_value)
                    except InvalidOperation:
                        messages.error(request, f"{criterion.name} must be a number.")
                        return redirect(request.path)
                    if numeric < criterion.minimum or numeric > criterion.maximum:
                        messages.error(
                            request,
                            f"{criterion.name} must be between {criterion.minimum:g} and "
                            f"{criterion.maximum:g}.",
                        )
                        return redirect(request.path)
                    answer.numeric_value = numeric
                    answer.choice_value = ""
                    answer.text_value = ""
                elif criterion.field_type == EvaluationCriterion.DROPDOWN:
                    if raw_value not in criterion.options:
                        messages.error(request, f"Choose a valid {criterion.name}.")
                        return redirect(request.path)
                    answer.choice_value = raw_value
                    answer.numeric_value = None
                    answer.text_value = ""
                else:
                    answer.text_value = raw_value
                    answer.numeric_value = None
                    answer.choice_value = ""
                answer.save()
            assignment_obj.status = RoundReviewAssignment.COMPLETE
            assignment_obj.submitted_at = timezone.now()
            assignment_obj.save(update_fields=["status", "submitted_at", "updated"])
            messages.success(request, "Round evaluation saved and marked complete.")
        return redirect(request.path)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            assignments = list(self._assignments().prefetch_related("round__criteria", "answers"))
            assignment = self._assignment()
            fields = []
            if assignment:
                answer_map = {answer.criterion_id: answer for answer in assignment.answers.all()}
                for criterion in assignment.round.criteria.all():
                    answer = answer_map.get(criterion.pk)
                    value = ""
                    if answer:
                        value = (
                            answer.numeric_value
                            if criterion.field_type == EvaluationCriterion.NUMERIC
                            else answer.choice_value
                            if criterion.field_type == EvaluationCriterion.DROPDOWN
                            else answer.text_value
                        )
                    fields.append({"criterion": criterion, "value": value})
            context.update(
                event=self.event,
                assignments=assignments,
                assignment=assignment,
                fields=fields,
            )
        return context
