# Decision 013: Separate source identities from people

## Goal and trust boundary

Conference memory must survive staff turnover without silently claiming that two
public records belong to the same person. A public schedule identifier is evidence
inside one source edition; it is not a globally unique human identity.

## Failure that forced the decision

The full #41 corpus exposed `R8PQYJ` in two PyLadiesCon editions for two different
people: Sarah Adigwe in 2023 and Marie-Louise Annan in 2024. The prior importer used
that value as a globally unique `HistoricalSpeaker.canonical_key`, so the later import
overwrote the person-facing record and combined their histories. Sarah also has the
distinct 2024 source identifier `8FBYYV`.

This is worse than a missing match. False recurrence can misdirect invitations,
review context, relationship notes, and buyer trust.

## Decision

Every source credit now receives an edition-scoped `HistoricalSourceIdentity`:

- explicit source value: `ext:<source-key>` within one edition;
- no source value: `credit:<talk-key>:<position>` within one edition.

The source identity maps to the provisional `HistoricalSpeaker` cluster used by the
existing UI. Cross-edition mappings created from legacy keys or normalized names remain
`legacy_unverified`; only an explicit operator link/relink/split decision can mark a
pair verified. Each decision records the prior and resolved cluster, action, reason,
HTTPS evidence, actor, timestamp, and monotonically unique version. Re-import updates
source metadata but never overwrites that mapping.

The UI excludes unverified clusters from returning-speaker cadence, labels speaker
briefs as provisional until at least two edition identities are verified, and exposes
the human decision/audit controls. A verified source record can then be handed into the
organization CRM without automatic duplicate merging.

## Corpus and release contract

The contracted corpus contains 13 series, 204 editions, 19,466 talks, 21,419 credits,
21,355 active edition-scoped source identities, and 14,068 provisional person clusters.
The PyLadies collision is conservatively split: Sarah's two source records remain
separate until reviewed, while Marie receives her own cluster.

Catalog analysis rejects any provisional canonical key that maps to multiple normalized
names. Production deployment atomically imports and verifies the full inventory before
protected smoke; carrying files in the image is not sufficient.

## Rejected alternatives

1. **Patch only the displayed name.** This preserves the false credit linkage.
2. **Namespace identifiers by conference family.** The observed collision occurred
   within one family across editions, so family scope is still too broad.
3. **Merge every matching normalized name.** Common names and spelling collisions create
   false positives across unrelated events.
4. **Delete uncertain records.** This destroys valid source evidence and hides the
   uncertainty the operator must resolve.

## Verification

`tests/test_conference_memory.py` covers atomic collision rejection, edition-scoped
identity creation, audited linking, actor/evidence requirements, re-import persistence,
verified-only recurrence, safe retirement on prune, and memory-to-CRM handoff.
`tests/test_history_coverage.py` locks the full identity inventory and collision guard.
`tests/test_operations_contract.py` requires strict corpus import/verification before
production smoke.
