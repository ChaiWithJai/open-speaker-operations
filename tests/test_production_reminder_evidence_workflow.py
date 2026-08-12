from pathlib import Path


def test_production_reminder_evidence_workflow_is_bounded_and_sanitized():
    workflow = Path(".github/workflows/verify-reminder-evidence.yml").read_text()

    assert "environment: production" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "speakerops_verify_reminder_evidence" in workflow
    assert '--event "$EVENT_SLUG" --as-of "$AS_OF"' in workflow
    assert "actual_sha" in workflow
    assert 'test "$actual_sha" = "$DEPLOYED_SHA"' in workflow
    assert 'printf %s "$APP_VERSION"' in workflow
    assert "container_sha" in workflow
    assert "container_image_id" in workflow
    assert "speakerops-due-speaker-reminders-daily" in workflow
    assert "worker_log" in workflow
    assert "celery_task_ids" in workflow
    assert "speakerops_seed" not in workflow
    assert "docker compose down" not in workflow
    assert "BUZZ_PRIVATE_KEY" not in workflow
    assert "rendered_body" not in workflow
    assert "speaker.email" not in workflow
