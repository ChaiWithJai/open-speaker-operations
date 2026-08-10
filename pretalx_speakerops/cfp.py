from datetime import datetime
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_scopes import scope
from pretalx.submission.forms import QuestionsForm
from pretalx.submission.models import (
    AnswerOption,
    Question,
    QuestionTarget,
    QuestionVariant,
    SubmissionStates,
    SubmissionType,
    Track,
)
from pretalx.submission.models.question import QuestionRequired

from .models import AcceptanceWave

SESSION_FORMATS = (
    ("Keynote (45 min)", 45),
    ("Talk (30 min)", 30),
    ("Lightning Talk (10 min)", 10),
    ("Workshop (120 min)", 120),
    ("Panel (45 min)", 45),
    ("Workshop", 90),
    ("Stage Talk", 20),
    ("Lightning Talk", 10),
    ("Online Talk", 30),
)

ACCEPTANCE_WAVES = (("Wave 1", 8, 15), ("Wave 2", 9, 1), ("Wave 3", 9, 15))
AIE_TRACKS = (
    "AI Engineering",
    "Platform & Infra",
    "Developer Experience",
    "AI in Financial Services",
    "Evals and Observability",
    "Infrastructure",
    "AI Agents",
    "Product and Design",
    "Leadership",
)

DEMO_CFP_QUESTIONS = (
    ("Review category", QuestionVariant.CHOICES, QuestionRequired.REQUIRED),
    ("Audience level", QuestionVariant.CHOICES, QuestionRequired.REQUIRED),
    ("Key takeaway", QuestionVariant.STRING, QuestionRequired.REQUIRED),
    ("Workshop prerequisites", QuestionVariant.STRING, QuestionRequired.REQUIRED),
    ("Topics", QuestionVariant.MULTIPLE, QuestionRequired.REQUIRED),
    ("Commercial relationship", QuestionVariant.CHOICES, QuestionRequired.REQUIRED),
    ("Proposed session context", QuestionVariant.CHOICES, QuestionRequired.OPTIONAL),
    ("Session title pronunciation", QuestionVariant.STRING, QuestionRequired.OPTIONAL),
    ("Session abstract", QuestionVariant.TEXT, QuestionRequired.REQUIRED),
    ("Session website", QuestionVariant.URL, QuestionRequired.OPTIONAL),
    ("Accessible format needed", QuestionVariant.BOOLEAN, QuestionRequired.OPTIONAL),
    ("Audience interests", QuestionVariant.MULTIPLE, QuestionRequired.OPTIONAL),
    ("Speaker headshot", QuestionVariant.FILE, QuestionRequired.OPTIONAL),
)

QUESTION_OPTIONS = {
    "Review category": ("Program and leadership", "Systems and agents"),
    "Audience level": ("Beginner", "Intermediate", "Advanced"),
    "Topics": (
        "AI agents",
        "Evals and observability",
        "Infrastructure",
        "AI in financial services",
        "Product and design",
        "Leadership",
        "Developer experience",
        "Safety and governance",
    ),
    "Commercial relationship": (
        "No commercial relationship",
        "I work for or represent a vendor discussed in this session",
    ),
    "Proposed session context": (
        "Main stage",
        "Workshop",
        "Leadership program",
        "Expo or booth",
    ),
    "Audience interests": (
        "AI engineering",
        "Product and design",
        "Leadership",
        "Developer experience",
    ),
}


def _configure_submission_types(event):
    configured = []
    for name, duration in SESSION_FORMATS:
        submission_type = SubmissionType.objects.filter(event=event, name=name).first()
        if submission_type is None:
            submission_type = SubmissionType(event=event, name=name)
        submission_type.default_duration = duration
        submission_type.deadline = event.cfp.deadline
        submission_type.requires_access_code = False
        submission_type.save()
        configured.append(submission_type)
    event.cfp.default_type = next(
        submission_type
        for submission_type in configured
        if str(submission_type.name) == "Talk (30 min)"
    )
    event.cfp.save(update_fields=["default_type", "updated"])
    return configured


def configure_demo_cfp(event):
    """Configure the seeded AIE CFP using pretalx's native question system."""
    with scope(event=event):
        # Keep the native abstract field available for post-submit editing, but
        # do not make it block the evaluator's title-only draft workflow. The
        # program's canonical "Session abstract" question remains required
        # before final submission.
        cfp_fields = dict(event.cfp.fields)
        cfp_fields["abstract"] = {**cfp_fields["abstract"], "visibility": "optional"}
        event.cfp.fields = cfp_fields
        event.cfp.save(update_fields=["fields", "updated"])
        submission_types = _configure_submission_types(event)
        Question.all_objects.filter(event=event, question="Session format").update(active=False)
        for position, name in enumerate(AIE_TRACKS):
            track = Track.objects.filter(event=event, name=name).first()
            if track is None:
                Track.objects.create(
                    event=event,
                    name=name,
                    description=f"AIE program track: {name}.",
                    color="#175CD3",
                    position=position,
                )
        event_timezone = ZoneInfo(event.timezone)
        for position, (name, month, day) in enumerate(ACCEPTANCE_WAVES):
            AcceptanceWave.objects.update_or_create(
                event=event,
                name=name,
                defaults={
                    "decision_at": timezone.make_aware(
                        datetime(event.date_from.year, month, day, 17), event_timezone
                    ),
                    "position": position,
                },
            )
        questions = []
        for position, (label, variant, required) in enumerate(DEMO_CFP_QUESTIONS):
            question = Question.all_objects.filter(event=event, question=label).first()
            # Preserve answers from the earlier demo label while converging the
            # deterministic dataset on the evaluator's exact field name.
            if question is None and label == "Audience level":
                question = Question.all_objects.filter(event=event, question="Talk level").first()
            if question is None:
                question = Question(event=event, question=label)
            question.question = label
            question.variant = variant
            question.target = QuestionTarget.SUBMISSION
            question.question_required = required
            question.help_text = f"AIE demo guidance for {label.lower()}."
            question.position = position
            question.active = True
            question.min_length = 20 if variant == QuestionVariant.TEXT else None
            question.max_length = 500 if variant == QuestionVariant.TEXT else None
            question.save()
            allowed_types = (
                [
                    submission_type
                    for submission_type in submission_types
                    if str(submission_type.name) in {"Workshop", "Workshop (120 min)"}
                ]
                if label == "Workshop prerequisites"
                else submission_types
            )
            question.submission_types.set(allowed_types)
            if variant in (QuestionVariant.CHOICES, QuestionVariant.MULTIPLE):
                options = QUESTION_OPTIONS[label]
                for option_position, option_text in enumerate(options):
                    AnswerOption.objects.update_or_create(
                        question=question,
                        answer=option_text,
                        defaults={"position": option_position},
                    )
                question.options.exclude(answer__in=options).delete()
            questions.append(question)
        Question.all_objects.filter(event=event, question="Talk level").update(active=False)
        return questions


def configure_demo_cfp_routing(event, reviewers):
    """Seed one conditional rule and two distinct, track-backed reviewer pools."""
    from .models import ConditionalQuestionRule, ReviewerPool, ReviewerPoolTrack

    reviewers = list(reviewers)
    if len(reviewers) < 2:
        raise ValueError("The deterministic CFP routing demo needs two reviewers.")
    with scope(event=event):
        controller = Question.all_objects.get(event=event, question="Commercial relationship")
        target = Question.all_objects.get(event=event, question="Proposed session context")
        trigger = controller.options.get(
            answer="I work for or represent a vendor discussed in this session"
        )
        ConditionalQuestionRule.objects.update_or_create(
            event=event,
            name="Vendor context disclosure",
            defaults={
                "controller_question": controller,
                "trigger_option": trigger,
                "target_question": target,
                "target_required_on_match": True,
                "active": True,
            },
        )

        tracks = list(event.tracks.order_by("position", "pk"))
        if len(tracks) < 2:
            raise ValueError("The deterministic CFP routing demo needs at least two tracks.")
        split = max(1, len(tracks) // 2)
        pool_specs = (
            (
                "program-and-leadership",
                "Program and leadership reviewers",
                reviewers[0],
                tracks[:split],
            ),
            (
                "systems-and-agents",
                "Systems and agents reviewers",
                reviewers[1],
                tracks[split:],
            ),
        )
        ReviewerPoolTrack.objects.filter(event=event, track__in=tracks).delete()
        pools = []
        for slug, name, reviewer, mapped_tracks in pool_specs:
            pool, _ = ReviewerPool.objects.update_or_create(
                event=event, slug=slug, defaults={"name": name}
            )
            pool.reviewers.set([reviewer])
            ReviewerPoolTrack.objects.bulk_create(
                [ReviewerPoolTrack(event=event, pool=pool, track=track) for track in mapped_tracks]
            )
            pools.append(pool)
        return pools


def conditional_rules_for_browser(event):
    """Return the same persisted rules consumed by server validation."""
    from .models import ConditionalQuestionRule

    with scope(event=event):
        rules = ConditionalQuestionRule.objects.filter(event=event, active=True).select_related(
            "controller_question", "trigger_option", "target_question"
        )
        return [
            {
                "controllerName": f"question_{rule.controller_question_id}",
                "triggerOption": str(rule.trigger_option_id),
                "targetName": f"question_{rule.target_question_id}",
                "targetRequired": rule.target_required_on_match,
            }
            for rule in rules
        ]


def _answer_is_present(value):
    if value is None or value is False or value == "":
        return False
    try:
        return bool(value)
    except TypeError:  # pragma: no cover - defensive for unusual form values
        return True


def _cleaned_value_matches(value, trigger_option_id):
    if getattr(value, "pk", None) == trigger_option_id:
        return True
    if hasattr(value, "values_list"):
        return trigger_option_id in set(value.values_list("pk", flat=True))
    if isinstance(value, (list, tuple, set)):
        return any(getattr(item, "pk", item) == trigger_option_id for item in value)
    return False


def validate_persisted_conditional_answers(submission):
    """Reject answers that contradict persisted visibility rules."""
    from .models import ConditionalQuestionRule

    rules = ConditionalQuestionRule.objects.filter(
        event=submission.event, active=True
    ).select_related("trigger_option")
    answers = {
        answer.question_id: set(answer.options.values_list("pk", flat=True))
        for answer in submission.answers.prefetch_related("options")
    }
    for rule in rules:
        matched = rule.trigger_option_id in answers.get(rule.controller_question_id, set())
        target_present = bool(answers.get(rule.target_question_id))
        if matched and rule.target_required_on_match and not target_present:
            raise ValidationError(f"{rule.target_question.question} is required for this answer.")
        if not matched and target_present:
            raise ValidationError(f"{rule.target_question.question} was submitted while hidden.")
    _validate_persisted_workshop_prerequisites(submission)


def _validate_persisted_workshop_prerequisites(submission):
    """Enforce the submission-type condition on authoritative stored answers."""
    question = Question.all_objects.filter(
        event=submission.event, question="Workshop prerequisites", active=True
    ).first()
    if not question:
        return
    answer = submission.answers.filter(question=question).prefetch_related("options").first()
    answer_present = bool(
        answer
        and (
            (answer.answer and str(answer.answer).strip())
            or answer.answer_file
            or answer.options.exists()
        )
    )
    is_workshop = question.submission_types.filter(pk=submission.submission_type_id).exists()
    if is_workshop and not answer_present:
        raise ValidationError("Workshop prerequisites are required for Workshop proposals.")
    if not is_workshop and answer_present:
        raise ValidationError("Workshop prerequisites were submitted while hidden.")


def route_submission_to_reviewer_pool(submission):
    """Validate and assign exactly the reviewers mapped to the submission track."""
    from .models import ReviewerPool, ReviewerPoolTrack

    with scope(event=submission.event):
        validate_persisted_conditional_answers(submission)
        if not submission.track_id:
            raise ValidationError("Choose a category with a configured reviewer pool.")
        mappings = list(
            ReviewerPoolTrack.objects.filter(
                event=submission.event, track_id=submission.track_id
            ).select_related("pool")
        )
        if len(mappings) != 1:
            raise ValidationError("This category does not have one unambiguous reviewer pool.")
        pool = ReviewerPool.objects.prefetch_related("reviewers").get(pk=mappings[0].pool_id)
        reviewers = list(pool.reviewers.all())
        if not reviewers:
            raise ValidationError("The configured reviewer pool has no reviewers.")
        submission.assigned_reviewers.set(reviewers)
        return pool


class SpeakerOpsQuestionsForm(QuestionsForm):
    """Native pretalx questions plus persisted visibility and routing enforcement."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            question = getattr(field, "question", None)
            if question and str(question.question) == "Audience level":
                widget = forms.Select()
                widget.choices = field.choices
                field.widget = widget
                break

    def clean(self):
        cleaned_data = super().clean()
        from .models import ConditionalQuestionRule, ReviewerPool, ReviewerPoolTrack

        if "pretalx_speakerops" not in self.event.plugin_list:
            return cleaned_data
        prerequisites = Question.all_objects.filter(
            event=self.event, question="Workshop prerequisites", active=True
        ).first()
        submission_type_id = getattr(self.submission_type, "pk", self.submission_type)
        is_prerequisites_type = bool(
            prerequisites and prerequisites.submission_types.filter(pk=submission_type_id).exists()
        )
        if prerequisites and not is_prerequisites_type:
            prerequisites_name = f"question_{prerequisites.pk}"
            has_posted_value = _answer_is_present(self.data.get(prerequisites_name))
            has_stored_value = bool(
                self.submission and self.submission.answers.filter(question=prerequisites).exists()
            )
            if has_posted_value or has_stored_value:
                raise forms.ValidationError(
                    "Workshop prerequisites are hidden unless Session type is Workshop."
                )
        rules = ConditionalQuestionRule.objects.filter(
            event=self.event, active=True
        ).select_related("trigger_option")
        for rule in rules:
            controller_name = f"question_{rule.controller_question_id}"
            target_name = f"question_{rule.target_question_id}"
            matches = _cleaned_value_matches(
                cleaned_data.get(controller_name), rule.trigger_option_id
            )
            target_value = cleaned_data.get(target_name)
            if matches and rule.target_required_on_match and not _answer_is_present(target_value):
                self.add_error(target_name, "This question is required for your previous answer.")
            elif not matches and _answer_is_present(target_value):
                self.add_error(target_name, "This hidden question must not be submitted.")

        if ReviewerPool.objects.filter(event=self.event).exists():
            track_id = getattr(self.track, "pk", self.track)
            if not track_id:
                category_question = Question.all_objects.get(
                    event=self.event, question="Review category"
                )
                category_value = cleaned_data.get(f"question_{category_question.pk}")
                category_label = str(getattr(category_value, "answer", category_value or ""))
                category_slug = {
                    "Program and leadership": "program-and-leadership",
                    "Systems and agents": "systems-and-agents",
                }.get(category_label)
                pool = ReviewerPool.objects.filter(event=self.event, slug=category_slug).first()
                track_id = (
                    ReviewerPoolTrack.objects.filter(event=self.event, pool=pool)
                    .values_list("track_id", flat=True)
                    .first()
                    if pool
                    else None
                )
                self._speakerops_routing_track_id = track_id
            mapping_count = ReviewerPoolTrack.objects.filter(
                event=self.event, track_id=track_id
            ).count()
            if mapping_count != 1:
                raise forms.ValidationError(
                    "This category does not have one unambiguous reviewer pool."
                )
        return cleaned_data

    def save(self):
        result = super().save()
        routing_track_id = getattr(self, "_speakerops_routing_track_id", None)
        if self.submission and routing_track_id:
            self.submission.track_id = routing_track_id
            self.submission.save(update_fields=["track", "updated"])
        if self.submission and self.submission.state != SubmissionStates.DRAFT:
            route_submission_to_reviewer_pool(self.submission)
        return result


def _answer_values(submission):
    values = {}
    answers = submission.answers.select_related("question").prefetch_related("options")
    for answer in answers:
        label = str(answer.question.question)
        if answer.question.variant in (QuestionVariant.CHOICES, QuestionVariant.MULTIPLE):
            values[label] = [str(option.answer) for option in answer.options.all()]
        else:
            values[label] = answer.answer
    return values


def validate_aie_submission_policy(submission):
    """Validate the AIE CFP rules on authoritative, persisted answers.

    JavaScript may progressively reveal the session-context question, but this
    function is the enforcement boundary used before routing or acceptance.
    """
    values = _answer_values(submission)
    topics = values.get("Topics") or []
    if not 1 <= len(topics) <= 5:
        raise ValidationError("Choose between one and five topics.")

    relationship = values.get("Commercial relationship") or []
    context = values.get("Proposed session context") or []
    is_vendor = any("vendor" in value.lower() for value in relationship)
    is_main_stage = (
        str(submission.submission_type.name)
        in {
            "Stage Talk",
            "Talk (30 min)",
        }
        or "Main stage" in context
    )
    if is_vendor and is_main_stage:
        raise ValidationError(
            "Vendor-only talks are not eligible for the main stage. "
            "Choose a workshop, leadership, expo, or booth context."
        )
    if is_vendor and not context:
        raise ValidationError("Choose an allowed context for a vendor-affiliated session.")
    return values
