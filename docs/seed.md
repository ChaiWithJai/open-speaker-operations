# SpeakerOps demo seed

Run after migrations:

```bash
PRETALX_CONFIG_FILE="$PWD/pretalx.cfg" \
  .venv/bin/python -m pretalx speakerops_seed
```

The command is idempotent and creates `speakerops-demo`, demo accounts, varied
pretalx proposal/review/schedule data, plugin onboarding work, and a recorded
mock Accelevents preview.

Demo credentials use the password `speakerops-demo`:

- `admin@example.org` — administrator
- `chair@example.org` — program chair
- `reviewer@example.org` — reviewer
- `speaker@example.org` — speaker
- `speaker2@example.org` — distinct second speaker for co-author and cross-speaker scoping

The integration record is a preview-only stub. No external credentials or
network calls are made.

The second speaker is deliberately a separate user record. Evaluator scenarios must
not map both speaker personas to `speaker@example.org`: doing so cannot prove co-author
identity, invitation boundaries, or cross-speaker authorization.

## Full conference-memory backfill

The event seed and the historical corpus are intentionally separate: reseeding the
judged event stays fast and does not silently rewrite 18,432 source-backed records.
Load and verify the complete known corpus explicitly after migrations or into a clean
environment:

```bash
python -m pretalx speakerops_history_coverage \
  pretalx_speakerops/data/conferences \
  --contract pretalx_speakerops/data/conference_history_contract.json --strict

python -m pretalx speakerops_import_history \
  pretalx_speakerops/data/conferences \
  --contract pretalx_speakerops/data/conference_history_contract.json \
  --prune --confirm-prune --verify \
  --report /tmp/speakerops-history-verification.json
```

The first command fails on catalog, edition, count, identity, digest, or provenance-gap
drift. The second performs one atomic import and then compares every database series,
edition, talk, speaker credit, and canonical speaker key with the contracted catalog.
The committed expectation is 13 series, 199 editions, 18,432 talks, 20,238 credits,
20,174 edition-scoped source identities, and 13,376 provisional person clusters;
120 declared gaps, 9 empty editions, 1,067 missing format labels,
and 5,590 missing track labels remain explicit rather than inferred. The additional
JSConf US 2009/2011/2012 and JSConf China 2012–2015 rows come from immutable
first-party repository branches. Their unavailable track labels remain explicit
instead of being guessed.

## Canonical demo timeline

- CFP opens: May 1, 2026 at 09:00 America/New_York
- CFP closes: June 30, 2026 at 23:59 America/New_York
- Judged walkthrough/rehearsal: August 9, 2026 at 12:00 America/New_York
- Program: August 10–12, 2026 in America/New_York
- Acceptance waves: August 15, September 1, and September 15 at 17:00 America/New_York

The seed derives speaker-task deadlines from acceptance time and keeps the two
conflict fixtures in the unpublished WIP schedule. The released schedule remains
the curated twelve-session program.
