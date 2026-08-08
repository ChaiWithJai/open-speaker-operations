# Decision: Reminders and resources

## Question

How can reminders and speaker resources reuse pretalx mail/storage boundaries
while remaining replay-safe and publication-controlled?

## Baseline and evidence

Pinned pretalx `2025.2.2` provides `pretalx.mail.models.MailTemplate`,
`MailTemplate.to_mail()`, and persisted `QueuedMail`. It also provides Django
app storage discovery. It does not provide the product's task reminder
audience receipt or versioned resource/wiki models.

## Cheaper seams rejected

A parallel mail sender would bypass pretalx's queue and mail audit. A single
resource text field would make drafts overwrite published content. Raw HTML
rendering would allow unsafe markup and uncontrolled embeds.

## Decision and invariants

Use pretalx `MailTemplate.to_mail()`/`QueuedMail` and plugin
`ReminderReceipt` rows keyed by event, task, speaker, and reminder key. Use
append-only `ResourceVersion` rows, sanitize an explicit HTML allowlist, allow
only approved iframe hosts, and render only published versions.

## Upgrade, rollback, and security impact

An upgrade could change `MailTemplate.to_mail()` rendering context or queue
fields, or Django storage behavior. Re-audit those APIs before upgrading.
Queued mails remain in pretalx; resource versions and receipts are plugin-owned.

## Automated proof

`tests/test_m2.py::test_reminder_replay_is_deduplicated` and
`test_resources_sanitize_and_only_publish_visible` prove queue dedupe and
publication/sanitization boundaries.
