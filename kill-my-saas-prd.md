# Product Requirements Document: Open Speaker Operations

| Field | Value |
|---|---|
| Status | Final — implementation baseline |
| Owner | Jai Bhagat |
| Last updated | 2026-08-08 |
| Target submission | 2026-08-12 22:00 PT |
| Product type | Open-source, self-hostable speaker and program operations system |

## 1. Summary

Open Speaker Operations is an open-source replacement for the subset of Sessionboard used by the AIE team. It connects the complete program-content workflow: call for speakers, submission review, acceptance, speaker onboarding, scheduling, communications, and publishing into Accelevents and public embeds.

The product is not a registration, ticketing, onsite-event, or attendee-engagement platform. Accelevents remains the registration and event-delivery system. This product becomes the system of record for speakers, proposals, sessions, onboarding tasks, and the working agenda.

## 2. Background and opportunity

The AIE team reports paying more than $40,000 annually for Sessionboard while using only a subset of its capabilities. Their operational problem is not the absence of event software; it is that the specialist content layer they need is bundled into an expensive closed-source product.

Prior art proves the workflow is tractable:

- [pretalx](https://github.com/pretalx/pretalx) provides open-source CFP, review, speaker communications, conflict-aware scheduling, publication, APIs, and plugins.
- [Indico](https://getindico.io/) provides mature abstract review, roles, rooms, and timetables for scientific events.
- [Conference Hall](https://github.com/conference-hall/conference-hall) provides an open CFP SaaS and reusable speaker profiles.
- [frab](https://github.com/frab/frab) proves that a Rails monolith can support submissions, speakers, talks, and conference schedules.
- Commercial products including Sessionboard, Sessionize, Oxford Abstracts, OpenWater, Cvent, and Accelevents validate demand but split between specialist speaker operations and full event suites.

The opportunity is a modern, focused, integration-friendly speaker-operations layer—not another complete event platform.

### 2.1 Market choice and product direction

The market separates into three groups:

| Group | Examples | What it proves | Why it is not our direction |
|---|---|---|---|
| Full event suites | Cvent, Bizzabo, RainFocus, Whova, Accelevents | Buyers value an integrated attendee/event system | Rebuilding registration, ticketing, exhibitors, and onsite tooling would dilute the speaker-operations problem |
| Commercial speaker/program tools | Sessionboard, Sessionize, Oxford Abstracts, Ex Ordo, OpenWater, X-CD/Cadmium | The exact workflow has budget and urgency | Closed platforms preserve cost and lock-in; several still require downstream event-platform integration |
| Open workflow foundations | pretalx, Indico, Conference Hall, frab, OpenReview | CFP, review, scheduling, and publication can be open and self-hosted | No single option provides the AIE-specific onboarding, operational dashboard, Accelevents export, and product polish as one focused flow |

The chosen product is an **open speaker-operations system of record** built on pretalx and extended for the AIE workflow. It owns speakers, proposals, reviews, onboarding work, program decisions, and schedule releases. Accelevents remains the downstream registration and attendee-delivery platform.

pretalx is selected because it has the greatest verified coverage of the acceptance sheet and mature implementations of the riskiest invariants: event scoping, speaker/proposal identity, review phases, queued mail, schedule releases, availability, collision warnings, public output, and APIs. A Rails 8 clean-room build is the contingency only if competition rules prohibit a disclosed derivative. Violet Rails is not selected because its CMS/CRM emphasis does not remove the conference-domain work that determines success.

## 3. Problem statement

Event-program teams currently coordinate submissions, reviewers, speakers, assets, reminders, schedules, and registration-platform data through either:

1. an expensive closed suite with unused breadth; or
2. disconnected forms, spreadsheets, inboxes, calendars, and file stores.

This creates manual re-entry, missed onboarding work, inconsistent review, schedule conflicts, stale public information, and vendor lock-in.

## 4. Product principles

1. **One connected lifecycle.** A proposal becomes an accepted session without re-entry.
2. **Human judgment remains authoritative.** AI supports review but never makes an irreversible acceptance decision.
3. **Operational state must be visible.** Staff should immediately know what is late, blocked, conflicted, unpublished, or unsynchronized.
4. **Integrate rather than replace.** Registration and attendee delivery stay in Accelevents.
5. **Open and portable.** The system must be self-hostable, documented, and deployable as a conventional container.
6. **Polish the critical path.** A reliable end-to-end workflow wins over broad but disconnected feature coverage.

## 5. Goals

### 5.1 Competition goals

- Demonstrate the complete path from public submission to published, synchronized session.
- Pass an independent AIE team evaluation using a deployed test environment.
- Deliver an open-source repository that another team can run locally.
- Make product decisions that result in a system the organizers would actually adopt.
- Provide fast, mobile-friendly public pages and responsive operational screens.

### 5.2 User goals

- Organizers can configure and operate a program without engineering assistance.
- Reviewers can score assigned proposals consistently and efficiently.
- Speakers can maintain their information and complete all required work from one portal.
- Program managers can construct an agenda without double-booking speakers or rooms.
- The AIE team can publish speaker/session data into Accelevents without manual re-entry.

## 6. Non-goals

- Ticketing, registration, payments, badges, check-in, attendee messaging, exhibitors, sponsors, floor plans, or a native attendee mobile app.
- Pixel-level cloning of Sessionboard.
- Autonomous AI acceptance or rejection.
- General-purpose CRM functionality beyond speakers and program participants.
- Bidirectional Accelevents synchronization in the MVP.
- Full i18n, enterprise SSO, SCIM, SOC 2 certification, or advanced compliance workflows during the competition.
- Supporting every calendar provider through authenticated two-way calendar sync. Standards-compliant ICS delivery is the MVP.

## 7. Personas and jobs to be done

| Persona | Primary job | Current failure |
|---|---|---|
| Program administrator | Configure and monitor the entire program lifecycle | Work is scattered across tools and people |
| Program chair | Select a coherent, high-quality program | Scores, notes, conflicts, and decisions are hard to compare |
| Reviewer | Evaluate only the proposals assigned to me | Rubrics and materials arrive inconsistently |
| Speaker | Submit once and know exactly what remains | Requests are buried across email threads and forms |
| Schedule manager | Place sessions across rooms and tracks | Double bookings and unavailable speakers are discovered late |
| Web/event operator | Publish accurate content downstream | Re-entering speaker and session data creates drift |

## 8. Core lifecycle

1. An organizer creates an event, tracks, rooms, categories, CFP dates, and a submission form.
2. A speaker creates or resumes a proposal and invites co-speakers if needed.
3. Submission rules validate the proposal and route it to the correct review pool.
4. Reviewers score assigned proposals against a configured rubric over one or more rounds.
5. A program chair accepts, rejects, waitlists, or requests changes.
6. Acceptance creates the session and speaker-onboarding plan without copying data.
7. Speakers complete required profile fields, forms, agreements, uploads, and availability.
8. Organizers monitor completion and send targeted or automatic reminders.
9. A schedule manager assigns sessions to times, rooms, and tracks with conflict warnings.
10. The team publishes a schedule revision, produces public embeds, sends calendar invitations, and synchronizes approved fields to Accelevents.

## 9. Functional requirements

Priorities use **P0** for competition-critical, **P1** for high-value completion, and **P2** for stretch work.

### 9.1 Identity, organizations, and authorization

- **P0:** Users authenticate securely and may hold different roles per event.
- **P0:** Roles include organizer, program chair, reviewer, and speaker.
- **P0:** Authorization prevents reviewers and speakers from accessing organizer-only data.
- **P1:** Organizers can invite users through expiring links.
- **P2:** Passwordless speaker access and enterprise SSO.

### 9.2 Event configuration

- **P0:** Create and edit event identity, timezone, dates, tracks, rooms, categories, session formats, and CFP window.
- **P0:** Maintain draft and published configuration states where publication affects public surfaces.
- **P1:** Clone configuration from an earlier event without copying people or submissions.

### 9.3 CFP and dynamic forms

- **P0:** Build a public form from text, long text, select, multiselect, boolean, URL, and file fields.
- **P0:** Configure required fields, help text, choices, validation, ordering, and category association.
- **P0:** Save and resume a draft before submission.
- **P1:** Conditional visibility based on earlier answers.
- **P1:** Route submissions by category, track, format, or answer.
- **P2:** Reusable form templates and calculated validation.

### 9.4 Proposals and speakers

- **P0:** One proposal may contain one or more speakers.
- **P0:** Proposal states include draft, submitted, under review, accepted, rejected, waitlisted, and withdrawn.
- **P0:** Preserve a timestamped state-transition history.
- **P0:** Speakers can maintain biography, headshot, contact information, organization, title, and links.
- **P1:** Internal tags, private notes, bulk filtering, and CSV export.

### 9.5 Review and selection

- **P0:** Configure criteria, scales, weights, instructions, and review rounds.
- **P0:** Assign reviewers manually or by category.
- **P0:** Reviewers see assigned proposals, provide criterion scores, comments, and a recommendation.
- **P0:** Program chairs see aggregates and individual reviews and retain final decision authority.
- **P1:** Blind-review mode and reviewer workload balancing.
- **P1:** AI-assisted rubric evaluation returns cited reasoning, confidence, and per-criterion suggestions.
- **P1:** Store AI model, prompt version, response, latency, and cost for auditability.
- **P2:** Duplicate-topic clustering and program-balance analysis.

### 9.6 Speaker onboarding portal

- **P0:** Acceptance creates a speaker-facing checklist from an onboarding template.
- **P0:** Tasks may request a profile field, form response, acknowledgement, headshot, slides, or supporting document.
- **P0:** Speakers see due date, status, instructions, and completion criteria.
- **P0:** Organizers see completion by speaker, session, task type, and due date.
- **P1:** Resource/wiki pages support rich text, links, and controlled HTML embeds.
- **P1:** Organizers can reopen completed work or waive a task with a reason.

### 9.7 Communications and calendar delivery

- **P0:** Create reusable email templates with event, speaker, session, task, and schedule variables.
- **P0:** Send to explicit speakers or filtered segments and retain a delivery log.
- **P0:** Queue email delivery and retry transient failures without blocking user requests.
- **P1:** Schedule reminders based on task status and due dates.
- **P1:** Generate standards-compliant ICS invitations for confirmed sessions, with stable identifiers for updates and cancellation.
- **P2:** Authenticated Google and Microsoft calendar connections.

### 9.8 Agenda and conflict detection

- **P0:** Create sessions, placeholders, rooms, tracks, and time slots.
- **P0:** Assign accepted sessions to a start time, duration, room, and track.
- **P0:** Detect speaker overlap, room overlap, speaker unavailability, and assignments outside event bounds.
- **P0:** Present a usable day/room schedule and allow schedule changes.
- **P1:** Drag-and-drop editing with optimistic updates and conflict feedback.
- **P1:** Draft schedule revisions and explicit publication.
- **P1:** Track, room, list, day, and week views.
- **P2:** Bulk moves and automated schedule suggestions.

### 9.9 Dashboard

- **P0:** Show outstanding tasks, missing assets, review progress, undecided proposals, schedule conflicts, and synchronization errors.
- **P0:** Every count links to the underlying filtered records.
- **P1:** Save filters and perform bulk actions.

### 9.10 Public publishing

- **P0:** Mobile-friendly public speaker gallery and schedule.
- **P0:** Embeddable read-only widgets with event-scoped configuration.
- **P0:** Only explicitly published records appear publicly.
- **P1:** Theme tokens, track/room filtering, and accessible keyboard navigation.
- **P1:** JSON feed and documented public API.

### 9.11 Accelevents integration

- **P0:** Map local speakers and sessions to Accelevents fields.
- **P0:** Perform an organizer-triggered, one-way synchronization from this system to Accelevents.
- **P0:** Sync operations are idempotent and retain external identifiers, status, error details, and attempt history.
- **P0:** Failed records can be retried without repeating successful writes.
- **P1:** Preview a synchronization plan before execution.
- **P1:** Automatically enqueue synchronization after schedule publication.

## 10. Experience requirements

- Organizers should always see the event context and current workflow state.
- Speaker pages must prioritize “what do I need to do next?” over navigation depth.
- Reviewer screens must support rapid keyboard-friendly scoring without losing work.
- Conflict messages must name the conflicting resource and competing assignment.
- Destructive or externally visible actions require confirmation and clear scope.
- Empty, loading, success, partial-failure, and retry states are required for integrations and bulk operations.
- Public pages and core portal workflows target WCAG 2.2 AA.

## 11. Non-functional requirements

### Performance

- P95 server response under 500 ms for ordinary authenticated reads at demonstration load.
- Public pages reach usable content in under 2 seconds on a typical mobile connection.
- Long-running email, AI, export, and synchronization operations execute asynchronously.
- Common organizer lists remain responsive with 5,000 proposals, 1,000 speakers, and 500 sessions per event.

### Reliability

- Database transactions protect state transitions and publication.
- External writes use idempotency keys or equivalent local deduplication.
- Jobs retry with bounded exponential backoff and surface terminal failure.
- Every deployment has a documented rollback path and database migrations are backward-compatible for one release.

### Security and privacy

- Enforce server-side authorization for every resource.
- Encrypt traffic in transit and use managed encryption at rest.
- Restrict uploaded file types and sizes; use signed access URLs for non-public assets.
- Protect public forms with rate limiting and bot controls.
- Never expose AI-provider or integration credentials to the browser.
- Record decisions, publication, integration writes, and administrative overrides in an audit log.

### Portability

- The application builds into an OCI-compatible `linux/amd64` container.
- Runtime-specific services are accessed through adapters.
- PostgreSQL is the authoritative relational database.
- Object storage uses an S3-compatible interface so Cloudflare R2 is supported.
- The repository provides one-command local startup with seeded demonstration data.

## 12. Success measures

### Competition acceptance

- A judge can complete the golden path without database or console intervention.
- The deployed site, source repository, setup instructions, and demonstration credentials are available before the deadline.
- The application detects intentionally seeded speaker and room conflicts.
- An accepted session produces onboarding tasks and appears in the published schedule.
- A synchronization dry run and a real or contract-tested Accelevents write are demonstrable.

### Product outcome

- Eliminate duplicate entry between proposal, accepted session, public schedule, and Accelevents.
- Organizers can identify all incomplete onboarding work in under 30 seconds.
- A speaker can understand and complete their remaining work without organizer explanation.
- Reviewers can score a proposal in one continuous screen.

## 13. Release scope and winning sequence

### Walking skeleton

- Event and roles
- Fixed but realistic CFP
- Proposal submission
- One review rubric
- Acceptance
- One onboarding task
- Manual schedule placement with conflict check
- Published public schedule
- Stubbed Accelevents adapter with recorded contract

### Competition MVP

- Configurable CFP fields
- Multi-criteria review and decisions
- Speaker profiles, uploads, and task dashboard
- Templated email
- Conflict-aware agenda UI
- Public speaker gallery and schedule embeds
- Real Accelevents one-way adapter if credentials and API access are available
- Containerized deployment and reproducible CI

The winning sequence is strict: prove the unbroken evaluator journey first, close every explicit acceptance-sheet item second, and add bonus infrastructure only after the primary deployment is stable. A feature that is not reachable in the seeded judge journey does not count as complete.

### Stretch

- Conditional form logic
- Multi-round and AI-assisted review
- Automated reminders and ICS updates
- Schedule versions and multiple views
- Airtable operational mirror
- Cloudflare Containers deployment target

## 14. Dependencies

- PostgreSQL
- S3-compatible object storage, preferably Cloudflare R2
- Transactional email provider
- AI model provider for optional assisted review
- Accelevents API access and a test event
- CI runner capable of building Docker images
- Production container host and Cloudflare account for DNS, CDN, WAF, Turnstile, R2, or Containers

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Attempting full Sessionboard parity | Disconnected, unfinished demo | Enforce golden-path scope and P0/P1/P2 priorities |
| Accelevents credentials or documentation unavailable | Cannot prove real sync | Implement adapter contract, recorded fixture tests, dry run, and visible blocked state |
| Dynamic form builder consumes schedule | Core lifecycle remains incomplete | Ship fixed field types first; conditional logic is P1 |
| Drag-and-drop consumes schedule | Agenda remains fragile | Make server-side placement and conflict rules P0; drag-and-drop P1 |
| AI produces inconsistent reviews | Loss of trust | Advisory only, schema validation, audit trail, and human decision authority |
| Cloudflare Containers instability or cold starts | Demo outage | Maintain a reliable primary container deployment; treat Cloudflare target as additive |
| Airtable used as primary storage | Integrity and concurrency failures | PostgreSQL is authoritative; Airtable is an optional mirror |

## 16. Decision gates and remaining questions

1. **Eligibility gate, first hour:** Does the competition permit a disclosed, license-compliant derivative? Current pretalx is AGPL-3.0 with additional Section 7 terms; if the answer is no, activate the Rails 8 fallback immediately.
2. What exact fields and operations are available in the AIE Accelevents account?
3. Is authenticated Google/Outlook calendar insertion required, or is direct ICS delivery acceptable?
4. Which onboarding tasks are mandatory for the evaluation dataset?
5. Is multi-event tenancy evaluated, or may the demo optimize for one event?
6. Does “Cloudflare infrastructure” include DNS, CDN, WAF, R2, and Turnstile, or specifically require application execution on Workers/Containers?
7. Is Airtable persistence a preference or merely bonus consideration?

Questions 2–7 affect implementation depth, not the product boundary. Defaults are: contract-tested one-way Accelevents adapter when credentials are absent; standards-compliant ICS delivery; configurable onboarding templates; multi-event-safe data scoping; Cloudflare edge/R2 as meaningful infrastructure participation; and PostgreSQL as authority with Airtable only as a rebuildable projection.

## 17. Acceptance-sheet traceability

| Canonical requirement | Product commitment | Priority | Proof |
|---|---|---:|---|
| Custom CFP forms, conditional logic, category routing | Configurable questions plus declarative visibility/routing rules | P0 | Seeded conditional submission routes to the expected review pool |
| Speaker portal, profiles, headshots, slides, support documents | One task-driven speaker workspace | P0 | Accepted speaker completes all artifacts without organizer access |
| Templates, reminders, calendar invites | Queued templates, due-date reminder plans, versioned ICS messages | P0 | Delivery log and update-safe calendar UID are visible |
| Scoring, multiple rounds, optional AI | Existing review phases plus auditable advisory AI suggestions | P0 human / P1 AI | Reviewer and chair journeys; human decision remains authoritative |
| Drag/drop schedule, conflicts, requested views | Preserve schedule editor; server-authoritative warnings | P0 | Seeded room and speaker collisions are detected before release |
| Outstanding onboarding dashboard | Derived task state with drill-down and bulk reminders | P0 | Every count resolves to its underlying records |
| One-way Accelevents integration | Previewed, idempotent, resumable export | P0 | Sandbox run or fixture-backed contract proof with visible blocked state |
| Portal resources/wiki and HTML embeds | Versioned resources with sanitized, allowlisted embeds | P1 | Speaker can safely view a published resource |
| Embeddable mobile gallery and schedule | Published, cacheable, responsive embeds | P0 | External-host fixture renders gallery and itinerary |
| Open repository and deployed site | Reproducible setup, seeded judge account, public HTTPS endpoint | P0 | Clean install and smoke suite pass before submission |

## 18. References

- [Competition brief](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/edit)
- [Sessionboard speaker management](https://www.sessionboard.com/capabilities/conference-speaker-management)
- [Sessionboard–Accelevents integration](https://www.sessionboard.com/integration/accelevents)
- [pretalx repository](https://github.com/pretalx/pretalx)
- [pretalx scheduling](https://docs.pretalx.org/user/schedule/)
- [Indico](https://getindico.io/)
- [Conference Hall](https://github.com/conference-hall/conference-hall)
- [frab](https://github.com/frab/frab)
- [pretalx architecture on DeepWiki](https://deepwiki.com/pretalx/pretalx)
- [pretalx schedule editor on DeepWiki](https://deepwiki.com/pretalx/pretalx/5.2-schedule-editor-interface)

## 19. Changelog

- 2026-08-08: Initial PRD created from the competition brief and prior-art analysis.
- 2026-08-08: Finalized the market choice, pretalx-first foundation, winning sequence, defaults, and requirement-to-proof matrix.
