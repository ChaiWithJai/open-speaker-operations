from django_scopes import scope
from pretalx.submission.models import AnswerOption, Question, QuestionTarget, QuestionVariant
from pretalx.submission.models.question import QuestionRequired

DEMO_CFP_QUESTIONS = (
    ("Session format", QuestionVariant.CHOICES, QuestionRequired.REQUIRED),
    ("Session title pronunciation", QuestionVariant.STRING, QuestionRequired.OPTIONAL),
    ("Session abstract", QuestionVariant.TEXT, QuestionRequired.REQUIRED),
    ("Session website", QuestionVariant.URL, QuestionRequired.OPTIONAL),
    ("Accessible format needed", QuestionVariant.BOOLEAN, QuestionRequired.OPTIONAL),
    ("Audience interests", QuestionVariant.MULTIPLE, QuestionRequired.OPTIONAL),
    ("Speaker headshot", QuestionVariant.FILE, QuestionRequired.OPTIONAL),
)

QUESTION_OPTIONS = {
    "Session format": ("Main stage", "Workshop", "Roundtable"),
    "Audience interests": (
        "AI engineering",
        "Product and design",
        "Leadership",
        "Developer experience",
    ),
}


def configure_demo_cfp(event):
    """Configure the seeded AIE CFP using pretalx's native question system."""
    with scope(event=event):
        submission_type = event.cfp.default_type
        questions = []
        for position, (label, variant, required) in enumerate(DEMO_CFP_QUESTIONS):
            question = Question.all_objects.filter(event=event, question=label).first()
            if question is None:
                question = Question(event=event, question=label)
            question.variant = variant
            question.target = QuestionTarget.SUBMISSION
            question.question_required = required
            question.help_text = f"AIE demo guidance for {label.lower()}."
            question.position = position
            question.active = True
            question.min_length = 20 if variant == QuestionVariant.TEXT else None
            question.max_length = 500 if variant == QuestionVariant.TEXT else None
            question.save()
            question.submission_types.set([submission_type])
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
        return questions
