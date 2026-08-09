# PR #14 Evaluation: Checklist Walkdown

**Pull Request:** #14 — "Implement the seven-screen Speaker Ops journey"
**Branch:** `agent/implement-speaker-ops-wireframes` → `main`
**Spec:** 1750-line diff, 17 new URL endpoints, 9 templates, 3 static assets, 1 new migration (ReviewRecommendation), 5 new screen tests.
**CI (claimed):** ruff format ✅ · ruff check ✅ · pytest 27 passed ✅ · context-graph ✅ · git diff --check ✅

This evaluation walks each item from the competition acceptance criteria (issue #1) against
what PR #14 actually implements, with file/line evidence. Grades: **MET** (realized, demoable),
**PARTIAL** (present but incomplete or relying on pretalx native without customization),
**NOT MET** (absent or unverified).

---

## Core Acceptance Criteria

### 1. Custom CFP forms with conditional logic and category routing
**Grade: PARTIAL**

PR #14 adds `configure_demo_cfp` (`pretalx_speakerops/cfp.py`) with seven questions using
pretalx's native question system: Session format (choices: Main stage/Workshop/Roundtable),
title pronunciation, abstract, website, accessible format, audience interests (multiple), and
headshot (file upload). The test (`test_cfp_format_and_interest_options_are_distinct`) verifies
format and interests are distinct option sets.

**Gap:** "Conditional logic and category routing" is explicitly listed as gap `P1-cfp-routing`
in `docs/context-graph.json` ("Conditional visibility and answer-based routing", status: gap,
blocked by P1/M5 scope). PR #14 does NOT implement conditional visibility or answer-based
routing — it adds flat questions only. The PR description claims a "draft-state indicator via
the supported plugin hook," but no draft indicator exists in the templates or CFP code I read.
The claim appears to describe intent, not implementation.

**Evidence:** `cfp.py:6-14` (flat questions), `tests/test_screens.py:153-164` (options test only).

---

### 2. Speaker portal for biographies, headshots, slides, and support documents
**Grade: MET**

The checklist (`checklist.html`) renders onboarding tasks per speaker. The seeded task
definitions (`onboarding/services.py:8-26 DEFAULT_DEFINITIONS`) cover: profile biography,
acknowledgement, headshot upload, slides upload, supporting document upload. The checklist
groups them by urgency (Needs your attention / Complete / Waived), shows progress
("N of M complete"), and renders per-task evidence forms (file upload, acknowledgement
checkbox, text response). The CFP also has a headshot file question.

**Evidence:** `templates/pretalx_speakerops/checklist.html:1-50`, `onboarding/services.py:8-26`.

---

### 3. Automated templated communications, reminders, and Gmail/Outlook/iCal-compatible invitations
**Grade: PARTIAL**

Reminders: `queue_reminders` (`onboarding/reminders.py`) uses pretalx `MailTemplate` and calls
`template.to_mail(...)` per pending task, storing `ReminderReceipt`. iCal: `released_ical`
(`program/calendar.py`) generates calendar output with stable UIDs, SEQUENCE increment on
change, and cancellation tracking via `ScheduleIcsIdentity`.

**Gaps:** (a) "Gmail/Outlook-compatible invitations" — reminders are *queued* (to_mail creates a
mail object) but actual *sending* depends on pretalx's celery mail queue, which is not
verified here. (b) The iCal output uses SEQUENCE and cancellation, which is correct for
iCal compatibility, but no test verifies the calendar content is parseable by Gmail/Outlook.
(c) No test exercises end-to-end mail delivery.

**Evidence:** `onboarding/reminders.py:7-42`, `program/calendar.py:16-51`.

---

### 4. Submission evaluation and scoring with multiple rounds and optional AI
**Grade: PARTIAL**

`ReviewerScoringView` (`views.py:212-313`) provides: keyboard-first scoring with draft-safe
autosave (`reviewer.js` debounced AJAX save, 700ms), weighted criteria
(`criterion.category.weight`), multiple rounds (`configure_review_rounds` creates Round 1 +
Round 2), and a `ReviewRecommendation` model ( Hold/Accept/Reject via migration 0006). The
reviewer queue is restricted to assigned proposals for non-orga users.

**Gap:** "Optional AI" scoring is not implemented — there is no AI-assisted scoring path.
(It's "optional" in the criteria, so this is not blocking, but it's absent.)

**Evidence:** `views.py:212-313`, `pretalx_speakerops/migrations/0006_reviewrecommendation.py`,
`static/pretalx_speakerops/reviewer.js`.

---

### 5. Drag-and-drop scheduling with speaker and room conflict detection
**Grade: PARTIAL**

Conflict detection is real: `AgendaReleaseView` (`views.py:314-361`) calls
`classify_warnings(schedule)` and computes `blocking` conflicts; release is blocked until
resolved, and the release POST requires `confirm_release=yes`. Conflicts are named with
competing session info. The dashboard reports conflict count.

**Gap:** "Drag-and-drop scheduling" is NOT implemented — no drag-and-drop UI exists in the
templates or JS. PR #14 relies on pretalx's native schedule editor (not customized). The
agenda/release gate is a read-only review + confirm flow, not a drag-and-drop scheduler.

**Evidence:** `views.py:314-361` (read-only agenda + confirm), no `drag`/`drop` in static assets.

---

### 6. List, day, week, track, and room schedule views
**Grade: PARTIAL**

PR #14 adds `PublishedEmbedView` (flat session list, embeddable, responsive) and
`PublishedGalleryView` (speaker gallery). pretalx natively provides day/week/track/room
schedule views via its feed system, which PR #14 reuses rather than replaces.

**Gap:** No custom list/day/week/track/room views are added — the embed is a single flat grid.
The criteria ask for distinct views; PR #14 provides an embed + gallery and leans on pretalx
native for the rest. Whether pretalx native views fully satisfy "day, week, track, and room"
is unverified.

**Evidence:** `views.py:558-596` (PublishedScheduleMixin + embed/gallery), `templates/.../embed.html`.

---

### 7. Real-time outstanding-onboarding dashboard
**Grade: MET** (with caveat)

`DashboardView` (`views.py:83-116`) reports real counts: tasks, missing_assets, reviewed,
undecided, conflicts, sync errors. The "Needs your attention" strip calls out overdue tasks,
blocked release, and sync errors. Missing-asset tracking is new in PR #14 (tasks filtered by
`completion_evaluator="upload"` without evidence).

**Caveat:** "Real-time" is page-load Django rendering, not WebSocket/polling. Counts are
current at load time but not live-updating. For a demo this is sufficient; for literal real-time
it is not.

**Evidence:** `views.py:83-116`, `templates/pretalx_speakerops/dashboard.html`.

---

### 8. Native one-way Accelevents integration
**Grade: MET**

`SyncConsoleView` (`views.py:380-426`) + `SyncPreviewView`/`SyncRunView` implement the full
flow: create preview → confirm (`confirm_sync=yes`, explicit confirmation required) → run →
retry failed items. `ExternalIdentity` maps local speakers to external IDs; the mock
(`mock_accelevents/server.py`) implements the captured contract. Run history shows per-item
status, errors, and attempt counts.

**Evidence:** `views.py:380-426`, `pretalx_speakerops/integrations/accelevents.py`,
`mock_accelevents/server.py`, `templates/.../sync_console.html`.

---

### 9. Speaker resources/wiki pages with controlled HTML embeds
**Grade: MET**

`ResourceView` (`views.py:534-548`) is public, lists resource versions, and renders
`version.body_html|safe` (controlled HTML). The `Resource`/`ResourceVersion` models support
versioning and publish state.

**Evidence:** `views.py:534-548`, `templates/.../resource.html`, `models.py:154-175`.

---

### 10. Embeddable mobile speaker gallery and schedule/itinerary
**Grade: PARTIAL**

`PublishedGalleryView` is responsive (viewport meta, `auto-fit` grid, mobile breakpoint) and
`PublishedEmbedView` is embeddable (standalone HTML, no app chrome). Both are released-only
(404 if no current schedule).

**Gap:** "itinerary" (a per-speaker personal schedule) is not clearly implemented. The embed
is a session list, not a personal itinerary view. Whether the speaker gallery + embed fully
satisfy "gallery and schedule/itinerary" is partially met.

**Evidence:** `views.py:591-596`, `templates/.../gallery.html`, `templates/.../embed.html`.

---

## Submission Criteria

| Criterion | Grade | Notes |
|-----------|-------|-------|
| Open-source repository | **MET** | AGPL-3.0, on GitHub |
| Deployed, testable site | **MET** | docker compose + tests pass |
| Submitted by Aug 12, 10 PM PT | **TBD** | deadline management, not code |
| Independent evaluation passes | **TBD** | depends on running site + judge |
| Critical journey works w/o DB/console | **PARTIAL** | seed handles setup, but celery worker needed for mail; some paths need manual celery |
| Product choices form a coherent system | **MET** | design tokens (`speakerops.css`), consistent card/panel/badge patterns, role-based nav |

---

## Bonus Considerations

| Bonus | Grade | Notes |
|-------|-------|-------|
| Meaningful Cloudflare infrastructure | **NOT MET** | no Cloudflare usage |
| Airtable persistence or projection | **NOT MET** | no Airtable |
| Forge instead of GitHub | **NOT MET** | GitHub |
| Strong speed/performance | **UNVERIFIED** | no perf tests or metrics |
| Documented API | **PARTIAL** | `docs/context-graph.json` traces requirements, but no formal API docs |

---

## Process & Testing

- **Tests:** 5 new screen tests in `test_screens.py` cover dashboard counts, reviewer save, agenda
  blocking, sync console + gallery render, and CFP options. These are integration-level and
  meaningful. The claimed "27 passed" includes pre-existing tests.
- **Design system:** `static/pretalx_speakerops/speakerops.css` introduces proper design tokens
  (CSS custom properties for color, radius, shadow) and reusable patterns
  (`.speakerops-card`, `.speakerops-panel`, `.speakerops-badge`, `.speakerops-task`). This is
  the strongest artifact in the PR — a coherent visual language.
- **Accessibility:** templates use `aria-labelledby`, `aria-label`, `aria-current`, `role`,
  `tabindex`, `<fieldset>/<legend>` for scoring. Reasonable a11y posture for the time budget.

---

## Where PR #14 Relies on pretalx Native (not customized)

PR #14 is honest about extending seams, but several criteria are satisfied by pretalx's built-in
behavior rather than Speaker Ops code:

- CFP form rendering (pretalx questions)
- Schedule day/week/track/room feeds (pretalx native)
- Drag-and-drop scheduling (pretalx native editor, not customized)
- Mail sending (pretalx celery queue)

This is defensible (the original architecture decision was "plugin, not fork") but means the
competition criteria are partially met by pretalx, not by this PR.

---

## Summary Table

| # | Criterion | Grade |
|---|-----------|-------|
| 1 | Custom CFP (conditional logic + routing) | **PARTIAL** — flat questions, no routing |
| 2 | Speaker portal (bio/headshot/slides/docs) | **MET** |
| 3 | Templated comms + iCal invitations | **PARTIAL** — queued, delivery unverified |
| 4 | Scoring, multiple rounds, optional AI | **PARTIAL** — no AI scoring |
| 5 | Drag-and-drop scheduling + conflicts | **PARTIAL** — conflicts yes, drag-drop no |
| 6 | List/day/week/track/room schedule views | **PARTIAL** — embed + gallery, rest native |
| 7 | Real-time onboarding dashboard | **MET** (page-load, not WebSocket) |
| 8 | Native one-way Accelevents integration | **MET** |
| 9 | Speaker resources/wiki + HTML embeds | **MET** |
| 10 | Embeddable mobile gallery + schedule/itinerary | **PARTIAL** — gallery + embed, no itinerary |
| | Open-source repo | **MET** |
| | Deployed, testable | **MET** |
| | Coherent system | **MET** |

**Bottom line:** PR #14 is a substantial, well-built implementation that delivers the
role-based journey surfaces and a real design system. Its strongest work is the reviewer
scoring UX, the sync console flow, and the design tokens. The largest gaps relative to the
competition checklist are **conditional CFP routing (P1, explicitly scoped out), drag-and-drop
scheduling (relies on pretalx native), and AI scoring (optional, absent).** Most "partial" grades
are because the criterion is satisfied by pretalx native rather than Speaker Ops code — a
conscious architectural trade-off, not an oversight.
