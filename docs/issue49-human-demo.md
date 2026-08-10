# Issues #41, #49, and #62 deterministic human benchmark demo

Use this as the repeatable benchmark rehearsal after reseeding `speakerops-demo`.
The paid Sonnet/Opus baseline is preserved separately. This guide replaces further
paid evaluator runs with explicit human evidence for the remaining rule, scoping,
handoff, and manual checks.

## Preconditions

- Record the commit and environment being demonstrated.
- Reseed through the approved environment procedure and verify the released
  `m3-demo` schedule exists.
- Use the seeded chair, reviewer, and speaker identities; do not expose credentials
  in screenshots, recordings, terminal output, or issue comments.
- Start with a fresh browser profile. Keep separate chair, reviewer, speaker, and
  logged-out windows so role scoping is visible rather than inferred.
- Record the before-state before every mutation and reload after every saved state.

## 1. CFP rules and reviewer scoping

1. As the speaker, open an existing proposal after the CFP deadline. Verify the form
   is read-only and the close-date explanation is visible. Attempt presenter-role,
   invitation, withdrawal, and discard actions; each must be absent, disabled, or
   rejected without changing the proposal.
2. As chair, open Abstract management. Create or select a blind round and assign
   exactly two named proposals to the seeded reviewer.
3. As reviewer, use the Speaker Operations entry point. Verify it lands on **Assigned
   round reviews**, contains exactly those two proposals, and contains no unassigned
   proposal.
4. Open a blind assignment and search the rendered page for the speaker and co-speaker
   names, biographies, companies, and affiliations. None may appear. Record numeric,
   dropdown, and text answers and save.
5. As chair, return to review progress/results. Verify completion updated, the same
   answers and comment are visible, the weighted result is correct, and an unreviewed
   row sorts below scored rows. Download the CSV and compare it with the table.
6. Trigger a reminder for a reviewer with outstanding work and capture the queued-mail
   or outbox confirmation.

## 2. Speaker and Content round trips

1. As speaker, update biography and headshot, reload, and confirm both persist.
2. As chair, open the speaker record. Verify the biography matches and the durable
   headshot responds successfully rather than rendering a broken thumbnail.
3. In the speaker checklist, capture an incomplete upload task, upload `slides.pdf`,
   and capture the completed state. Upload a replacement with the same filename.
4. Expand version history. Verify v1 and v2, timestamps, **Current/latest**, old-version
   download, and speaker/organizer comments with authors and timestamps.
5. As chair, open **Content & files**. Filter by speaker and status; verify the row shows
   speaker, session, due date, explicit completion state, original filename, upload
   date, two versions, and current version.
6. Approve one session's content and leave another pending. In a logged-out window,
   verify only the approved session appears in the public widget/feed.
7. Select two uploaded deliverables, choose session grouping, and generate the ZIP.
   Repeat with one deselected. Inspect the archives: only selected latest versions may
   appear, with the requested grouping and no prior version.

## 3. Agenda rules and release handoff

1. Place **Taming 40-Minute CI** on Day 1 at 10:00 in Room 2A. Reload and verify the
   placement remains.
2. Place a second session in the same room/time. Verify the action is blocked or a
   visible room-conflict warning appears.
3. Move the second session elsewhere. Verify the warning clears immediately and stays
   cleared after reload.
4. Generate and apply an Agenda Assist proposal. Verify it includes accepted WIP
   sessions, produces no room/speaker overlaps, and does not leave accepted sessions
   incorrectly classified as unscheduled.
5. Release through the Speaker Operations release gate using its suggested unique
   version. Verify success without HTTP 500, then confirm the released session in a
   logged-out public schedule without re-entry.

## 4. Public widgets and organizer handoff

1. Open the public Sessions surface. Search `Raman` and record every returned title;
   compare the set with Priya Raman's published schedule entries.
2. Open Agenda without a day query. Verify **All days** is selected and three dated
   sections are present. Disable JavaScript and confirm all three remain readable.
   Re-enable JavaScript, select each day, and verify both the “Showing …” label and
   session content change.
3. Add two sessions to **My itinerary**, reload, remove one, and export ICS. Import the
   ICS into a calendar and verify title, date/time, and room.
4. As chair, open **Embed & share**. Select Sessions, Speakers, Agenda, My itinerary,
   and Gallery in turn. Exercise theme, field density, search, track, format, room, and
   output-format controls. Copy the generated snippet or URL and open its public target.
   For iframe/script output, render it on a different origin and verify interaction.
5. In Speakers/Gallery, confirm profiles contain curated biographies and no evaluator
   sentinel text. Temporarily request a broken headshot URL and verify the initial
   fallback appears without a broken-image icon.

## 5. Speaker CRM and Program Memory differentiator

1. Open organization-level **Speaker CRM**. Capture Program Memory totals, provenance,
   verified/provisional identity language, top companies, and the no-invented-contact
   policy. Treat provisional identities as candidates, not verified people.
2. Search Priya, combine company and tag filters, save a segment, reload it, and verify
   selected state, active-filter summary, result count, tags, notes, and history persist.
3. Import the same CSV twice. The second import must create zero contacts and report
   exact-email rows as updated/unchanged. A same-name/different-email row must remain an
   explicit duplicate-review candidate.
4. Move Marcus through pipeline stages, save a timestamped note, reload, and verify the
   transition history.
5. Add Marcus to DevFlow Conf 2027. Open DevFlow as the authorized chair and verify his
   identity and biography in its speaker roster. Confirm a user without DevFlow manage
   permission cannot see DevFlow in the picker or mutate it with a crafted request.
6. Select two contacts and log personalized outreach. Verify resolved merge fields and
   one timestamped history row per recipient. Do not claim delivery: this workflow is
   intentionally log-only until a real mail integration is built.

## 6. Manual artifact checks

- Inspect confirmation, decision, invitation, reviewer-reminder, and deliverable-reminder
  mail in an approved inbox or application outbox. Record recipient, subject, relevant
  title/task/deadline, and timestamp without exposing credentials.
- Open the downloaded headshot and both old/current slide files to verify integrity.
- Inspect selected/deselected ZIP contents and grouping.
- Import itinerary ICS into a real calendar and verify all fields.
- Preserve conflict before/action/after/reload screenshots.

## Evidence record

For each step capture criterion, route, persona, expected result, observed result,
timestamp, commit, and one private screenshot. Mark each row **pass**, **fail**, or
**blocked**; never convert missing evidence into a pass. Preserve the original all-days
view and at least two selected-day states so content switching is demonstrated rather
than inferred. Keep credentials, inbox tokens, private email bodies, and API keys out of
the evidence bundle.
