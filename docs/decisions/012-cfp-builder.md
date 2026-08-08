# Decision 012: Reuse pretalx's CFP question and draft flow

## Goal and architectural depth

The competition goal is a judgeable CFP → review journey. PRD §9.3 requires
the public form to configure text, long text, select, multiselect, boolean,
URL and file fields, requiredness, help text, choices, ordering and category
association, then save and resume a draft. This is a reuse decision at the
pretalx domain boundary, not a new application workflow.

## Question

Do we build a plugin-owned CFP builder and submission flow, or configure the
pinned pretalx implementation and expose proof in the seeded journey?

## Baseline verified in pretalx 2025.2.2

`pretalx.submission.models.question.QuestionVariant` provides string, text,
URL, boolean, file, choices and multiple-choice variants. `Question` stores
requiredness, help text, ordering, length and numeric validation, and
many-to-many associations to tracks and submission types. `AnswerOption` stores
choices. `pretalx.submission.forms.question.QuestionsForm` builds the public
fields and saves `Answer` records.

`pretalx.cfp.flow.QuestionsStep` places that form in the public submission
wizard. `pretalx.cfp.flow.FormFlowStep` persists intermediate data in the CFP
session, while `InfoStep.done` creates a `Submission` in `draft` state when
the draft action is selected. `DedraftMixin` reloads that draft for the
authenticated speaker, and the stock template exposes “Save draft” and
“Submit proposal”.

## Options and trade-offs

1. **Build a plugin form system.** This would give complete control but would
   duplicate field validation, file handling, answer persistence, draft
   security and resume semantics. It would also create a second CFP boundary
   for judges to understand.
2. **Fork or patch pretalx.** This could alter the wizard directly, but it
   violates the pinned-upstream/no-fork constraint and creates upgrade debt.
3. **Reuse and seed pretalx questions.** This preserves mature public form and
   draft behavior. The cost is that AIE-specific conditional routing remains
   out of scope, and the demo must make the configured questions visible
   rather than relying on an organiser to discover them.

## How the choice was made

We inspected the installed pinned source and added
`tests/test_cfp.py::test_seeded_cfp_renders_accepts_all_p0_field_types_and_resumes_draft`.
The test verifies every P0 variant, category association, requiredness, public
rendering, answer validation/persistence, and draft-backed submission setup.
The seed configures the seven AIE-shaped questions through
`pretalx_speakerops.cfp.configure_demo_cfp`.

The first implementation temptation was to add a plugin route because the
existing demo journey had no explicit CFP step. We abandoned that: the
upstream wizard already provides the protected path and a second route would
make the judge journey less coherent. Conditional visibility and answer-based
routing are deliberately left as a P1/M5 gap.

## Upgrade and operational cost

The plugin depends on pretalx's pinned model/form/flow symbols and must
re-audit them on every pretalx upgrade. The seed is demonstration data, not a
general organiser-facing question authoring UI. File validation and storage
remain pretalx behavior, including its accepted extension policy.

## Heuristic

Use the mature upstream seam when it already owns the required behavior; spend
the plugin budget on proof and judge surfacing rather than parallel CRUD.
