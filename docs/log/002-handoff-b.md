# Work unit 002: M2 onboarding victory

- **Intent:** Make onboarding evidence-backed, ordered, replay-safe, and
  visible to speakers and organisers.
- **Time box:** M2, with the protected journey taking priority over a complete
  CMS or mail product.
- **Ran:** Added templates, evaluator keys, uploads, resource versions,
  reminders, role teams, filtered drill-downs, reopen/waive, and seed evidence.
  Ran Ruff, full pytest, fresh migrate/seed, and seed replay.
- **Failed:** The first completion button mutated task state directly; seeded
  role users had no memberships; generated schedules had accidental rather
  than deliberate conflicts.
- **Abandoned:** Parallel mail and role systems were rejected. Pretalx
  `MailTemplate`/`QueuedMail`, teams, and configured storage were reused.
- **What we would do differently:** Make every state mutation use the executor
  before exposing the first form.
- **Demo relevance:** Counts had to link to rows and reconcile, and the speaker
  had to see the next action; those were tested rather than inferred.
