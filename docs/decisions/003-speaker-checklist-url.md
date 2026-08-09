# Decision: Speaker checklist URL

## Question

How can speakers reach their next-action checklist without adding a new
pretalx navigation signal or colliding with an existing public route?

## Goal and architecture depth

The goal is a speaker-facing “what do I do next?” surface without turning the
plugin choice into a pretalx fork. This is a low-level routing/UI decision
bounded by record 001, not a change to pretalx's agenda domain.

## Baseline and evidence

Pinned pretalx `2025.2.2` defines organiser hooks in
`pretalx/orga/signals.py`: `nav_event`, `nav_global`, `nav_event_settings`, and
`speaker_form`; source search found no speaker-area or CfP navigation signal.
`pretalx/agenda/urls.py` already owns `<slug:event>/speaker/<code>/`, so the
apparently natural `/speaker/checklist/` path resolves to
`pretalx.agenda.views.speaker.SpeakerView`.

## Cheaper seams rejected

Configuration cannot add a speaker link. A core navigation signal or template
override would patch upstream for a single link despite the existing public
URL seam. Reusing `/speaker/<code>/` would collide with pretalx's route and
would not identify the logged-in speaker's event task projection.

The quick failed attempt used `/speaker/checklist/`; pretalx's
`<event>/speaker/<code>/` route captured it and produced the wrong view. That
concrete collision, plus the verified absence of a speaker navigation signal,
made a standalone event URL the smallest working seam.

## How the choice was made

The spike requested `/speaker/checklist/` through Django's resolver and saw
pretalx's speaker route capture it. Source search then verified the missing
signal, and the replacement URL was tested through the logged-in client.

## Decision and invariants

Use the plugin-owned event URL
`/<event>/speaker-operations/checklist/`. `EventContextMixin` checks
authenticated speaker membership inside `scope(event=...)`; organiser links
and future mail links can point to the same URL.

## Upgrade, rollback, and security impact

An upgrade could add a conflicting route or introduce a speaker navigation
signal. Re-audit `pretalx/orga/signals.py` and `pretalx/agenda/urls.py` before
changing the URL. Rollback removes only plugin routes/templates. Server-side
speaker membership remains mandatory even if a link leaks.

The cost is a link that is not native to pretalx's speaker navigation; mail,
dashboard, or later upstream hooks must provide discovery. A future upstream
speaker hook could make this decision obsolete.

## Automated proof

`tests/test_acceptance_journey.py::test_golden_path_crosses_plugin_boundaries` and
`tests/test_onboarding_operations.py::test_roles_are_scoped_to_surfaces` prove speaker access and
organiser/reviewer denial.
