# Reminders and resources

## Context

Pretalx provides persisted `MailTemplate` and `QueuedMail` models. Speaker
guidance needs drafts, published versions, and controlled embeds.

## Decision

Reminder planning uses pretalx `MailTemplate.to_mail()` and `QueuedMail`, with
plugin-owned `ReminderReceipt` rows for stable deduplication. Resource versions
are plugin-owned and sanitize HTML through an explicit tag/attribute allowlist
plus an iframe host allowlist. Only versions with `published_at` are rendered
to speakers.

## Consequences

Mail remains visible to pretalx's existing queue tooling. Resource publishing
is append-only and leaves prior versions auditable.
