#!/usr/bin/env python3
"""Read-only HTTP smoke journey for the seeded Speaker Operations deployment."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from http.cookiejar import CookieJar


@dataclass
class Result:
    surface: str
    status: int
    milliseconds: float
    final_url: str


def request(opener, url, *, data=None, headers=None, timeout=15):
    request_headers = {
        "User-Agent": "speakerops-protected-smoke/1.0",
        "Accept": "text/html,application/xhtml+xml",
        **(headers or {}),
    }
    encoded = urllib.parse.urlencode(data).encode() if data is not None else None
    request_object = urllib.request.Request(url, data=encoded, headers=request_headers)
    started = time.perf_counter()
    response = opener.open(request_object, timeout=timeout)
    body = response.read().decode("utf-8", errors="replace")
    elapsed = (time.perf_counter() - started) * 1000
    return response, body, elapsed


def csrf_token(body):
    match = re.search(
        r'name=(?:["\'])?csrfmiddlewaretoken(?:["\'])?[^>]*'
        r'value=(?:["\'])?([^"\'\s>]+)',
        body,
        re.I,
    ) or re.search(
        r'value=(?:["\'])?([^"\'\s>]+)(?:["\'])?[^>]*'
        r'name=(?:["\'])?csrfmiddlewaretoken(?:["\'])?',
        body,
        re.I,
    )
    if not match:
        raise RuntimeError("login page did not expose a CSRF token")
    return match.group(1)


def assert_surface(surface, response, body, elapsed, expected_path, marker, *, alternatives=None):
    final_path = urllib.parse.urlparse(response.geturl()).path
    if response.status != 200:
        raise RuntimeError(f"{surface}: expected HTTP 200, received {response.status}")
    expected_markers = {expected_path: marker, **(alternatives or {})}
    expected_marker = expected_markers.get(final_path)
    if expected_marker is None:
        expected = ", ".join(repr(path) for path in expected_markers)
        raise RuntimeError(f"{surface}: landed on {final_path!r}, expected one of {expected}")
    if expected_marker not in body:
        raise RuntimeError(f"{surface}: missing protected marker {expected_marker!r}")
    return Result(surface, response.status, round(elapsed, 1), response.geturl())


def authenticated_surface(
    base_url, event, email, password, login_path, path, marker, timeout, *, alternatives=None
):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    login_url = urllib.parse.urljoin(base_url, login_path)
    _, login_body, _ = request(opener, login_url, timeout=timeout)
    response, body, elapsed = request(
        opener,
        login_url,
        data={
            "csrfmiddlewaretoken": csrf_token(login_body),
            "login_email": email,
            "login_password": password,
        },
        headers={"Referer": login_url},
        timeout=timeout,
    )
    return (
        assert_surface(
            email.split("@", 1)[0],
            response,
            body,
            elapsed,
            path,
            marker,
            alternatives=alternatives,
        ),
        opener,
    )


def public_surface(base_url, surface, path, marker, timeout, *, mobile=False):
    headers = {}
    if mobile:
        headers["User-Agent"] = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Mobile/15E148 speakerops-smoke"
        )
    opener = urllib.request.build_opener()
    response, body, elapsed = request(
        opener, urllib.parse.urljoin(base_url, path), headers=headers, timeout=timeout
    )
    result = assert_surface(surface, response, body, elapsed, path, marker)
    if mobile and not re.search(r"name=['\"]?viewport", body, re.I):
        raise RuntimeError("mobile-gallery: responsive viewport metadata is missing")
    return result


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--event", default="speakerops-demo")
    parser.add_argument("--password-env", default="SPEAKEROPS_SMOKE_PASSWORD")
    parser.add_argument("--timeout", type=float, default=15)
    return parser.parse_args()


def main():
    args = parse_args()
    password = os.environ.get(args.password_env)
    if not password:
        raise RuntimeError(f"set {args.password_env}; credentials are never accepted on argv")
    base_url = args.base_url.rstrip("/") + "/"
    event = urllib.parse.quote(args.event, safe="")
    cfp_login = f"/{event}/login/"
    orga_login = f"/orga/event/{event}/login/"
    results = []

    speaker, _ = authenticated_surface(
        base_url,
        event,
        "speaker@example.org",
        password,
        cfp_login,
        f"/{event}/speaker-operations/checklist/",
        "What do I need to do next?",
        args.timeout,
    )
    results.append(speaker)
    reviewer, _ = authenticated_surface(
        base_url,
        event,
        "reviewer@example.org",
        password,
        orga_login,
        f"/orga/{event}/speaker-operations/round-review/",
        "Assigned round evaluations",
        args.timeout,
        alternatives={
            f"/orga/{event}/speaker-operations/reviewer/": "Score assigned proposals",
        },
    )
    results.append(reviewer)
    chair, chair_opener = authenticated_surface(
        base_url,
        event,
        "chair@example.org",
        password,
        orga_login,
        f"/orga/{event}/speaker-operations/",
        "Program command center",
        args.timeout,
    )
    results.append(chair)
    native_schedule_path = f"/orga/event/{event}/schedule/"
    response, body, _ = request(
        chair_opener,
        urllib.parse.urljoin(base_url, native_schedule_path),
        timeout=args.timeout,
    )
    assert_surface(
        "native-schedule",
        response,
        body,
        0,
        native_schedule_path,
        "id=app",
    )
    if not re.search(r"/static/main-[a-f0-9]+\.js", body):
        raise RuntimeError("native-schedule: built schedule editor asset is missing")
    sync_path = f"/orga/{event}/speaker-operations/sync-console/"
    response, body, elapsed = request(
        chair_opener, urllib.parse.urljoin(base_url, sync_path), timeout=args.timeout
    )
    results.append(
        assert_surface("sync", response, body, elapsed, sync_path, "Accelevents synchronization")
    )
    results.append(
        public_surface(
            base_url,
            "embed",
            f"/{event}/speaker-operations/embed/",
            "Published program",
            args.timeout,
        )
    )
    results.append(
        public_surface(
            base_url,
            "mobile-gallery",
            f"/{event}/speaker-operations/gallery/",
            "Meet the speakers",
            args.timeout,
            mobile=True,
        )
    )
    print(
        json.dumps(
            {
                "ok": True,
                "surfaces": [asdict(result) for result in results],
                "checks": ["native-schedule-editor-assets"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError) as error:
        print(f"protected smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
