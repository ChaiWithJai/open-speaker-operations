import mimetypes
from pathlib import Path, PurePath

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View
from pretalx.person.models import SpeakerProfile

from .models import SpeakerOperationsProfile
from .views import EventContextMixin

MAX_HEADSHOT_BYTES = 5 * 1024 * 1024
ALLOWED_HEADSHOT_TYPES = {
    "JPEG": (".jpg", ".jpeg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


class SpeakerPortalProfileForm(forms.Form):
    biography = forms.CharField(
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 7, "class": "form-control"}),
        help_text="Shown to organizers and on approved public speaker surfaces.",
    )
    social_url = forms.URLField(
        max_length=500,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "https://"}),
        help_text="One professional profile or personal website using HTTPS.",
    )
    headshot = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": "image/png,image/jpeg,image/webp"}
        ),
        help_text="PNG, JPEG, or WebP; maximum 5 MB.",
    )

    def __init__(self, *args, has_headshot=False, **kwargs):
        self.has_headshot = has_headshot
        super().__init__(*args, **kwargs)

    def clean_social_url(self):
        value = self.cleaned_data["social_url"]
        if not value.startswith("https://"):
            raise forms.ValidationError("Use an HTTPS social or professional profile URL.")
        return value

    def clean_headshot(self):
        upload = self.cleaned_data.get("headshot")
        if not upload:
            if not self.has_headshot:
                raise forms.ValidationError("Upload a headshot before saving your profile.")
            return None
        if upload.size > MAX_HEADSHOT_BYTES:
            raise forms.ValidationError("Headshots must be 5 MB or smaller.")
        image_format = getattr(getattr(upload, "image", None), "format", "")
        allowed = ALLOWED_HEADSHOT_TYPES.get(image_format)
        suffix = Path(upload.name).suffix.lower()
        content_type = getattr(upload, "content_type", "")
        if not allowed or suffix not in allowed[:-1] or content_type != allowed[-1]:
            raise forms.ValidationError("Upload a valid PNG, JPEG, or WebP image.")
        upload.seek(0)
        return upload


class SpeakerPortalProfileView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/speaker_portal_profile.html"

    def _records(self):
        speaker_profile, _ = SpeakerProfile.objects.get_or_create(
            event=self.event,
            user=self.request.user,
        )
        operations_profile, _ = SpeakerOperationsProfile.objects.get_or_create(
            event=self.event,
            speaker=self.request.user,
        )
        return speaker_profile, operations_profile

    def _form(self, *, data=None, files=None):
        speaker_profile, operations_profile = self._records()
        return SpeakerPortalProfileForm(
            data=data,
            files=files,
            has_headshot=bool(self.request.user.avatar),
            initial={
                "biography": speaker_profile.biography or "",
                "social_url": operations_profile.social_url,
            },
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            event=self.event,
            form=kwargs.get("form") or self._form(),
            speaker=self.request.user,
            assignments=self.request.user.submissions.filter(event=self.event)
            .distinct()
            .order_by("title", "pk"),
        )
        return context

    def post(self, request, event):
        form = self._form(data=request.POST, files=request.FILES)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form), status=400)

        with transaction.atomic():
            speaker_profile, operations_profile = self._records()
            speaker_profile.biography = form.cleaned_data["biography"]
            speaker_profile.save(update_fields=["biography", "updated"])
            operations_profile.social_url = form.cleaned_data["social_url"]
            if headshot := form.cleaned_data.get("headshot"):
                operations_profile.headshot_original_filename = headshot.name
                operations_profile.headshot_uploaded_at = timezone.now()
                request.user.avatar = headshot
                request.user.avatar_thumbnail = None
                request.user.avatar_thumbnail_tiny = None
                request.user.get_gravatar = False
                request.user.save(
                    update_fields=[
                        "avatar",
                        "avatar_thumbnail",
                        "avatar_thumbnail_tiny",
                        "get_gravatar",
                    ],
                    skip_gravatar_processing=True,
                )
            operations_profile.save(
                update_fields=[
                    "social_url",
                    "headshot_original_filename",
                    "headshot_uploaded_at",
                    "updated",
                ]
            )

        messages.success(
            request, "Profile saved. Organizers now see the same biography, link, and headshot."
        )
        return redirect(
            reverse(
                "plugins:speakerops:speakerops_speaker_profile",
                kwargs={"event": self.event.slug},
            )
        )


class SpeakerSelfHeadshotView(EventContextMixin, View):
    """Serve the signed-in speaker's own avatar without exposing all media."""

    def get(self, request, event):
        if not request.user.avatar:
            raise Http404
        request.user.avatar.open("rb")
        return FileResponse(
            request.user.avatar.file,
            filename=PurePath(request.user.avatar.name).name,
            content_type=mimetypes.guess_type(request.user.avatar.name)[0] or "image/jpeg",
        )
