from django_scopes import scope
from pretalx.submission.models import Question

from pretalx_speakerops.integrations.buzz.cfp_reads import cfp_surface, cfp_surface_message
from pretalx_speakerops.models import EvaluationRound, ReviewerPool


def _digest(event):
    with scope(event=event):
        return {
            "questions": Question.all_objects.filter(event=event).count(),
            "rounds": EvaluationRound.objects.filter(event=event).count(),
            "pools": ReviewerPool.objects.filter(event=event).count(),
            "cfp_updated": event.cfp.updated,
        }


def test_exact_cfp_surface_prompt_has_typed_evidence_roles_and_canonical_links(event):
    before = _digest(event)

    report = cfp_surface(event.slug, base_url="https://speakerops.example")
    message = cfp_surface_message(event.slug, base_url="https://speakerops.example")

    assert report["event"]["slug"] == event.slug
    assert report["cfp"]["deadline"] == event.cfp.deadline.isoformat()
    assert report["cfp"]["native_submit_path"] == event.urls.submit
    assert "Review category" in {
        str(question["question"]) for question in report["cfp"]["questions"]
    }
    assert [role["user_type"] for role in report["role_guide"]] == [
        "submitter or speaker",
        "reviewer",
        "chair or organiser",
    ]
    assert {source["resource"] for source in report["sources"]} == {
        "cfp-public-guide",
        "review-queue",
        "cfp-routing-console",
    }
    assert {source["resource"]: source["url"] for source in report["sources"]} == {
        "cfp-public-guide": f"https://speakerops.example/go/cfp-public-guide/{event.slug}/",
        "review-queue": f"https://speakerops.example/go/review-queue/{event.slug}/",
        "cfp-routing-console": (f"https://speakerops.example/go/cfp-routing-console/{event.slug}/"),
    }
    assert all(
        source["url"].startswith("https://speakerops.example/go/") for source in report["sources"]
    )
    assert report["mutation_performed"] is False
    assert report["generated_at"]
    assert report["trace"]
    assert "# CFP submission and review surface" in message
    assert "## Which user type to use" in message
    assert "## Authoritative sources" in message
    assert "Mutation performed: no" in message
    assert _digest(event) == before
