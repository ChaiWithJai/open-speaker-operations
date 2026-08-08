import os
import uuid

import pytest
from django.core.management import call_command
from pretalx.event.models import Event
from pretalx.person.models import User


@pytest.fixture
def event(db):
    os.environ.setdefault("DJANGO_SUPERUSER_EMAIL", "admin@test.example.org")
    os.environ.setdefault("DJANGO_SUPERUSER_PASSWORD", "test-password")
    os.environ.setdefault("PRETALX_INIT_ORGANISER_NAME", "Test Organiser")
    os.environ.setdefault("PRETALX_INIT_ORGANISER_SLUG", "test-organiser")
    call_command("init", interactive=False, verbosity=0)
    slug = f"test-{uuid.uuid4().hex[:8]}"
    call_command("create_test_event", slug=slug, stage="schedule", seed=7, verbosity=0)
    return Event.objects.get(slug=slug)


@pytest.fixture
def users(db):
    return {
        role: User.objects.create_user(
            email=f"{role}-{uuid.uuid4().hex[:8]}@example.org",
            name=role.title(),
            password="test-password",
            is_administrator=role == "chair",
        )
        for role in ("chair", "speaker", "reviewer")
    }
