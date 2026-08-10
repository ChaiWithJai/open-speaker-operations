# Issue #49 deterministic human demo

Use this as a short, repeatable handoff rehearsal after reseeding `speakerops-demo`.
It is human verification guidance, not a substitute for the authenticated evaluator.

## Preconditions

- Record the commit and environment being demonstrated.
- Reseed through the approved environment procedure and verify the released
  `m3-demo` schedule exists.
- Use the seeded chair and speaker identities; do not expose credentials in evidence.

## Rule and public-handoff walkthrough

1. As the seeded speaker, open an existing proposal after the seeded CFP deadline.
   Verify the edit form is read-only, the closed-CFP explanation is visible, and
   presenter-role, invitation, withdrawal, and draft-discard POSTs cannot mutate data.
2. Open the public Sessions surface. Search `Raman` and record every returned title;
   compare the set with Priya Raman's published schedule entries.
3. Open Agenda without a day query. Verify **All days** is selected and three dated
   sections are present. Disable JavaScript and confirm all three remain readable.
   Re-enable JavaScript, select each day, and verify both the “Showing …” label and
   session content change.
4. As the chair, open **Embed & share**. Select Sessions, Speakers, Agenda, My itinerary,
   and Gallery in turn. Exercise theme, field density, search, track, format, room, and
   output-format controls; copy the generated snippet or URL and open its public target.
5. In Speakers/Gallery, confirm profiles contain curated biographies and no evaluator
   sentinel text. Temporarily request a broken headshot URL and verify the initial
   fallback appears without a broken-image icon.

## Evidence record

For each step capture route, persona, expected/observed result, timestamp, and one
private screenshot. Preserve the original all-days view and at least two different
selected-day states so content switching is demonstrable rather than inferred.
