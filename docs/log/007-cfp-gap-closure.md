# Work log 007: Close the CFP builder gap

## Intent

Close the remaining P0 context-graph gap without building a parallel CFP
system. Time box: one focused pass on the protected CFP → review journey.

## What we verified

The pinned pretalx 2025.2.2 source already provides the required P0 seam:
`QuestionVariant`, `Question`, `AnswerOption`, `QuestionsForm`,
`QuestionsStep`, draft `SubmissionStates.DRAFT`, and `DedraftMixin`.
The source supports all seven requested field types, requiredness, help text,
choices, ordering, category association through submission types/tracks,
validation, and save/resume.

## Correction

Added a seeded AIE-shaped CFP with string, long text, select, multiselect,
boolean, URL and file questions. Added proof that the public form renders,
accepts and persists answers, and that the draft submission path is available
for resume. The context graph now marks the P0 CFP row complete and names the
seeded judge step. Conditional visibility and answer-based routing remain an
explicit P1/M5 gap.

## Failed or abandoned approaches

The abandoned approach was to create plugin-owned CFP routes and models. That
would have duplicated pretalx's mature wizard and obscured the judge journey.
No new CFP domain model was needed. The remaining cost is re-auditing these
upstream symbols when pretalx changes.

## What we would do differently

The CFP proof should have been made a first-class seeded step during M0 rather
than left as an unproven graph row until after M4. The context graph caught the
missing demo evidence; the cheapest recovery was configuration plus tests.
