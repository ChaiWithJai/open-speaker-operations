# Conference memory catalog

This directory is the provenance-backed input to the Speaker Operations conference memory.
It is deliberately metadata-only: names, talk titles, published format/track labels,
recording links, and source timestamps. Source biographies and abstracts are not
republished unless their licensing is separately verified.

## Completion contract

Each conference series declares its crawl scope in `source_policy.scope`. A scope is
complete when every discoverable first-party schedule edition in that declaration is
represented and every unrecoverable omission is listed in
`source_policy.known_gaps`. A known gap is not invented data and does not disappear on
refresh; it is a machine-readable object with:

- `item`: the missing edition, session, or field range;
- `reason`: why it could not be recovered from the public source;
- `source_url`: the public page that proves or contextualizes the gap, when available
  (legacy HTTP is allowed only in this non-imported gap ledger).

Every edition and talk has its own `source_url` and `source_updated_at`. Speaker credits
inherit talk provenance unless the source exposes a stronger speaker-specific URL.
Fields enriched from a distinct organizer source retain `field_provenance` with
that source URL, its retrieval timestamp, and the deterministic matching method.
Missing format or track labels remain empty in JSON and import as
`Not provided by source`; they are never inferred.

## Validate and import

```bash
python -m pretalx speakerops_history_coverage \
  pretalx_speakerops/data/conferences \
  --contract pretalx_speakerops/data/conference_history_contract.json \
  --strict

python -m pretalx speakerops_import_history \
  pretalx_speakerops/data/conferences \
  --contract pretalx_speakerops/data/conference_history_contract.json \
  --prune --confirm-prune --verify \
  --report /tmp/speakerops-history-verification.json
```

Imports are atomic and idempotent. They update records with the same series, edition,
and talk keys. Records absent from a later source file are preserved by default. The
destructive refresh mode requires both `--prune` and `--confirm-prune`.

The committed contract locks the normalized catalog digest, every expected edition
key, per-series and global talk/credit/speaker counts, and the exact accounting totals
for known gaps, empty editions, missing formats, and missing tracks. `--verify` also
compares every series, edition, talk, credit, and canonical speaker identity in the
database to the catalog; missing or unexpected records roll the import back. The JSON
report is an untracked run artifact, not a substitute for the committed contract.

## Refresh procedure

1. Revisit the declared official/archive sources and obey their current access rules.
2. Update only observed metadata; never infer speakers, formats, or tracks.
3. Set the affected `source_updated_at` values to the actual retrieval time.
4. Update structured `known_gaps` and the sibling human-readable source-gap ledger.
5. Run strict coverage without changing the contract and review every reported drift.
6. After source review, generate a candidate with `--write-contract /tmp/contract.json`,
   inspect its diff, and replace the committed contract only when the changed corpus
   and provenance accounting are intentional.
7. Import into an isolated database twice and confirm exact verification on both runs.
8. Review identity collisions before any confirmed prune.

The starter catalog in the parent directory is a small import example. It is not the
historical completeness artifact and must not be used as closure evidence for #41.
