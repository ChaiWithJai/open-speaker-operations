from django import forms
from django.db import transaction
from django.db.models import Q, QuerySet
from pretalx.person.models import User
from pretalx.submission.models import AnswerOption, Question, Track

from .models import ConditionalQuestionRule, ReviewerPool, ReviewerPoolTrack


def _empty_queryset(model):
    """Build an empty queryset without invoking a django-scopes manager."""
    return QuerySet(model=model, using=None).none()


class ConditionalQuestionRuleForm(forms.ModelForm):
    controller_question = forms.ModelChoiceField(queryset=_empty_queryset(Question))
    trigger_option = forms.ModelChoiceField(queryset=_empty_queryset(AnswerOption))
    target_question = forms.ModelChoiceField(queryset=_empty_queryset(Question))

    class Meta:
        model = ConditionalQuestionRule
        fields = (
            "name",
            "controller_question",
            "trigger_option",
            "target_question",
            "target_required_on_match",
            "active",
        )

    def __init__(self, *args, event, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)
        self.fields["controller_question"].queryset = Question.all_objects.filter(
            event=event, active=True
        ).order_by("position")
        self.fields["target_question"].queryset = Question.all_objects.filter(
            event=event, active=True
        ).order_by("position")
        self.fields["trigger_option"].queryset = AnswerOption.objects.filter(
            question__event=event
        ).select_related("question")

    def clean(self):
        cleaned_data = super().clean()
        controller = cleaned_data.get("controller_question")
        target = cleaned_data.get("target_question")
        trigger = cleaned_data.get("trigger_option")
        if controller and target and controller == target:
            self.add_error("target_question", "Choose a different target question.")
        if controller and trigger and trigger.question_id != controller.pk:
            self.add_error("trigger_option", "Choose an option from the controller question.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.event = self.event
        if commit:
            instance.save()
        return instance


class ReviewerPoolForm(forms.Form):
    pool_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=160)
    slug = forms.SlugField(max_length=80)
    tracks = forms.ModelMultipleChoiceField(queryset=_empty_queryset(Track))
    reviewers = forms.ModelMultipleChoiceField(queryset=_empty_queryset(User))

    def __init__(self, *args, event, pool=None, **kwargs):
        self.event = event
        self.pool = pool
        if pool and not args and "data" not in kwargs:
            kwargs["initial"] = {
                "pool_id": pool.pk,
                "name": pool.name,
                "slug": pool.slug,
                "tracks": pool.track_mappings.values_list("track_id", flat=True),
                "reviewers": pool.reviewers.values_list("pk", flat=True),
            }
        super().__init__(*args, **kwargs)
        self.fields["tracks"].queryset = Track.objects.filter(event=event).order_by(
            "position", "name"
        )
        self.fields["reviewers"].queryset = (
            User.objects.filter(
                Q(teams__all_events=True, teams__organiser=event.organiser)
                | Q(teams__limit_events=event),
                teams__is_reviewer=True,
            )
            .distinct()
            .order_by("email")
        )

    def clean_pool_id(self):
        pool_id = self.cleaned_data.get("pool_id")
        if not pool_id:
            return None
        self.pool = ReviewerPool.objects.filter(event=self.event, pk=pool_id).first()
        if not self.pool:
            raise forms.ValidationError("Choose a reviewer pool from this event.")
        return pool_id

    def clean(self):
        cleaned_data = super().clean()
        tracks = cleaned_data.get("tracks")
        if tracks is not None:
            conflicts = ReviewerPoolTrack.objects.filter(event=self.event, track__in=tracks)
            if self.pool:
                conflicts = conflicts.exclude(pool=self.pool)
            if conflicts.exists():
                self.add_error("tracks", "Each category can map to only one reviewer pool.")
        return cleaned_data

    @transaction.atomic
    def save(self):
        if not self.is_valid():  # pragma: no cover - view validates before saving
            raise ValueError("Cannot save an invalid reviewer pool form.")
        pool = self.pool or ReviewerPool(event=self.event)
        pool.name = self.cleaned_data["name"]
        pool.slug = self.cleaned_data["slug"]
        pool.save()
        pool.reviewers.set(self.cleaned_data["reviewers"])
        pool.track_mappings.all().delete()
        ReviewerPoolTrack.objects.bulk_create(
            [
                ReviewerPoolTrack(event=self.event, pool=pool, track=track)
                for track in self.cleaned_data["tracks"]
            ]
        )
        return pool
