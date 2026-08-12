"""Read-only Buzz answer for the CFP submission and review surface."""

from __future__ import annotations

from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.submission.models import Question

from pretalx_speakerops.canonical_links import RESOURCES
from pretalx_speakerops.models import EvaluationRound, ReviewerPool

DEFAULT_BASE_URL = "http://localhost:8000"


def _event(event_slug):
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    return event


def _go(base_url, resource, event_slug):
    return f"{base_url.rstrip('/')}/go/{resource}/{event_slug}/"


def _resource(resource):
    return next(item for item in RESOURCES if item.resource == resource)


def cfp_surface(event_slug, base_url=DEFAULT_BASE_URL):
    """Describe the authoritative CFP surfaces, roles, and configuration."""
    event = _event(event_slug)
    cfp = event.cfp
    now = timezone.now()
    urls = {
        "submitter": _go(base_url, "cfp-public-guide", event.slug),
        "reviewer": _go(base_url, "review-queue", event.slug),
        "chair": _go(base_url, "cfp-routing-console", event.slug),
    }

    with scope(event=event):
        cfp_is_open = cfp.is_open
        questions = list(
            Question.all_objects.filter(event=event, active=True)
            .order_by("target", "position", "pk")
            .values("question", "target", "variant", "question_required")
        )
        rounds = list(
            EvaluationRound.objects.filter(event=event, active=True)
            .order_by("position", "pk")
            .values("name", "opens_at", "closes_at", "blinded")
        )
        pools = list(
            ReviewerPool.objects.filter(event=event)
            .order_by("name", "pk")
            .values_list("name", flat=True)
        )

    native_fields = []
    for name, settings in sorted(cfp.fields.items()):
        native_fields.append(
            {
                "name": name,
                "visibility": settings.get("visibility", "unknown"),
                "required": settings.get("required", False),
            }
        )

    sources = []
    for role, resource in (
        ("submitter", "cfp-public-guide"),
        ("reviewer", "review-queue"),
        ("chair", "cfp-routing-console"),
    ):
        registry = _resource(resource)
        sources.append(
            {
                "role": role,
                "resource": resource,
                "url": urls[role],
                "route_name": registry.route_name,
                "audience": registry.audience,
                "exactness": registry.exactness,
            }
        )

    return {
        "event": {"slug": event.slug, "name": str(event.name)},
        "cfp": {
            "is_open": cfp_is_open,
            "opening": cfp.opening.isoformat() if cfp.opening else None,
            "deadline": cfp.deadline.isoformat() if cfp.deadline else None,
            "native_submit_path": event.urls.submit,
            "native_fields": native_fields,
            "questions": questions,
        },
        "review": {"rounds": rounds, "reviewer_pools": pools},
        "role_guide": [
            {
                "user_type": "submitter or speaker",
                "use_for": (
                    "Explore the public CFP guide; the native submission action is the "
                    f"separate `{event.urls.submit}` path."
                ),
                "url": urls["submitter"],
            },
            {
                "user_type": "reviewer",
                "use_for": "Explore only that reviewer's assigned review queue.",
                "url": urls["reviewer"],
            },
            {
                "user_type": "chair or organiser",
                "use_for": "Inspect CFP configuration, conditional fields, and routing.",
                "url": urls["chair"],
            },
        ],
        "sources": sources,
        "generated_at": now.isoformat(),
        "trace": [
            "Read the event-scoped pretalx CFP configuration and active questions.",
            "Read active SpeakerOps review rounds and reviewer pools.",
            "Resolved role-specific links from the canonical resource registry.",
        ],
        "mutation_performed": False,
    }


def cfp_surface_message(event_slug, base_url=DEFAULT_BASE_URL):
    """Render the exact Fizz answer as a compact, source-linked report."""
    report = cfp_surface(event_slug, base_url=base_url)
    cfp = report["cfp"]
    state = "open" if cfp["is_open"] else "closed"
    lines = [
        f"# CFP submission and review surface — {report['event']['name']}",
        "",
        f"**CFP state:** {state}",
        f"**Opening:** {cfp['opening'] or 'not configured'}",
        f"**Deadline:** {cfp['deadline'] or 'not configured'}",
        f"**Native submission path:** `{cfp['native_submit_path']}`",
        "",
        "## Which user type to use",
    ]
    for role in report["role_guide"]:
        lines.append(f"- **{role['user_type']}** — {role['use_for']} {role['url']}")
    lines.extend(
        [
            "",
            "## Configured submission surface",
            f"- Native fields: {len(cfp['native_fields'])}",
            f"- Active custom questions: {len(cfp['questions'])}",
            "- Questions: "
            + (", ".join(str(item["question"]) for item in cfp["questions"]) or "none"),
            "",
            "## Review surface",
            "- Active rounds: "
            + (", ".join(str(item["name"]) for item in report["review"]["rounds"]) or "none"),
            "- Reviewer pools: " + (", ".join(report["review"]["reviewer_pools"]) or "none"),
            "",
            "## Authoritative sources",
        ]
    )
    for source in report["sources"]:
        lines.append(
            f"- `{source['resource']}` ({source['audience']}, {source['exactness']}): "
            f"{source['url']}"
        )
    lines.extend(
        [
            "",
            f"Generated: {report['generated_at']}",
            "Trace of inference:",
            *(f"- {step}" for step in report["trace"]),
            "Mutation performed: no",
        ]
    )
    return "\n".join(lines)
