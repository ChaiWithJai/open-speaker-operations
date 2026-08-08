# Decision records

## North star

The repository is trying to win the competition by rapidly prototyping a
fully working, **demoable** solution aligned to the original documentation.
Anything not reachable in the seeded judge journey does not count as complete.
The decision series exists to make that work and its decay visible, not to
reward architecture that never reaches the judge.

These records make each extension seam auditable while serving that journey.
They explain why SpeakerOps uses the cheapest seam that preserves pretalx's
invariants, and what debt was accepted to keep the demo moving.

## Seam preference

For every gap, prefer these options in order:

1. Configuration or an existing pretalx setting.
2. Plugin-owned models, views, jobs, and templates.
3. Existing pretalx signals or domain services.
4. A UI override or narrowly scoped extension hook.
5. A core patch, only when atomic enforcement or the required journey is
   impossible otherwise.

## When a record is required

Write a record for every meaningful boundary choice: ownership of state,
authorization, transaction timing, public/private publication, external
integration, storage/security policy, or any choice between pretalx reuse and
plugin behavior.

## Re-auditing a record

Start with the pinned dependency version in `pyproject.toml`. Read every named
upstream source file and test, then inspect the named repository acceptance test.
Confirm that the baseline behavior still exists, that the rejected cheaper seams
remain insufficient, and that the acceptance test still exercises the invariant.
If an upstream upgrade changes a named symbol or behavior, update the record and
its test before upgrading.
