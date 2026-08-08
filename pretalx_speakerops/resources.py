from urllib.parse import urlparse

import bleach
from django.utils import timezone

from .models import ResourceVersion

ALLOWED_TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "a", "h2", "h3", "iframe"]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "iframe": ["src", "title", "allow", "allowfullscreen"],
}
ALLOWED_IFRAME_HOSTS = {"www.youtube.com", "youtube.com", "player.vimeo.com", "vimeo.com"}


def sanitize_resource_html(body: str) -> str:
    cleaned = bleach.clean(body, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    for token in ("src=", "href="):
        if token in cleaned and "javascript:" in cleaned.lower():
            raise ValueError("Unsafe resource URL")
    for fragment in cleaned.split("src=")[1:]:
        host = urlparse(fragment.split('"', 2)[1].strip("'")).hostname
        if host and host not in ALLOWED_IFRAME_HOSTS:
            raise ValueError("Iframe host is not allowed")
    return cleaned


def publish_resource(resource, body, actor):
    body = sanitize_resource_html(body)
    version = resource.versions.order_by("-version").first()
    next_version = (version.version + 1) if version else 1
    return ResourceVersion.objects.create(
        event=resource.event,
        resource=resource,
        version=next_version,
        body_html=body,
        published_at=timezone.now(),
        created_by=actor,
    )


def create_resource_version(resource, body, actor, publish=False):
    body = sanitize_resource_html(body)
    version = resource.versions.order_by("-version").first()
    return ResourceVersion.objects.create(
        event=resource.event,
        resource=resource,
        version=(version.version + 1) if version else 1,
        body_html=body,
        published_at=timezone.now() if publish else None,
        created_by=actor,
    )
