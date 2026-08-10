# AI Engineer historical backfill provenance and gaps

Retrieved and normalized on 2026-08-09, with World's Fair 2026 refreshed on
2026-08-10 UTC. `source_updated_at` is the upstream
record timestamp where one was published; otherwise it is the retrieval time.
The catalog deliberately retains metadata and links, not the source abstracts
or speaker biographies.

## Coverage

| Edition | Talks with credited speakers | Official source |
| --- | ---: | --- |
| AI Engineer Summit 2023 | 53 | <https://www.ai.engineer/summit/2023/schedule> (`__NEXT_DATA__`) |
| AI Engineer World's Fair 2024 | 156 | <https://www.ai.engineer/worldsfair/2024/schedule> (`__NEXT_DATA__`) |
| AI Engineer World's Fair 2025 | 271 | <https://www.ai.engineer/worldsfair/2025/schedule> and its linked <https://www.ai.engineer/sessions-speakers-details.json> |
| AI Engineer Code Summit 2025 | 66 | <https://www.ai.engineer/code/2025/schedule> (the page's first-party JSON download payload) |
| AI Engineer Europe 2026 | 159 | <https://www.ai.engineer/europe/speakers.json> (162 speaker records with embedded sessions, deduplicated by title/day/time/room) |
| AI Engineer World's Fair 2026 | 561 | <https://www.ai.engineer/worldsfair/2026/sessions.json> and <https://www.ai.engineer/worldsfair/2026/speakers.json> (`scheduleVersion: 4945`) |
| AI Engineer NYC 2026 | 0 | <https://www.ai.engineer/nyc/2026> |
| AI Engineer World's Fair 2027 | 0 | <https://www.ai.engineer/worldsfair/2027> |

Total: 8 editions, 1,266 sessions, and 1,514 speaker credits.

## Explicit gaps and exclusions

- NYC 2026 and World's Fair 2027 are announced editions, but their official
  pages do not publish a speaker program as of retrieval. They remain edition
  records with zero talks; no agenda was synthesized. The 2027 placeholder has
  no dates because its first-party page does not publish them.
- World's Fair 2026 publishes 561 confirmed schedule entries. Fifteen have no
  speaker names and one credits the unresolved placeholder `TBD — Sonar`, which
  is absent from the 552-record speaker directory. All sessions remain in the
  corpus, but no identities are invented for those missing credits.
- Forty-four speakerless schedule blocks were excluded: 10 from Summit 2023,
  24 from World's Fair 2024, and 10 from Code Summit 2025. They are
  registration, food, expo, break, reception, or afterparty blocks rather than
  credited talks.
- The World's Fair 2025 dump leaves 45 session formats and 139 tracks blank,
  and Europe 2026 leaves 44 tracks blank. Those values remain empty rather
  than being inferred from titles or rooms. Summit 2023 is different: its
  official schedule explicitly says all talks use a single track, so all 53
  records are enriched as `Single track` with field-level source provenance.
- The global first-party `llms.txt` lists World's Fair 2025 as June 25–27, but
  the event-specific page and every dated row in its official 271-session JSON
  say June 3–5. The dataset follows the more specific event sources and records
  the upstream conflict in the machine-readable gap ledger.
- Abstracts and biographies are intentionally empty. Titles, credited speakers,
  formats, tracks, recording links, source URLs, and provenance timestamps are
  retained.

World's Fair 2026 feed ETags, raw SHA-256 digests, and the shared schedule version
are preserved in its edition snapshot so a refresh cannot silently redefine the
reviewed corpus. The AI Engineer robots policy allowed general access when retrieved and stated
`Content-Signal: search=yes,ai-train=no,use=reference`; this backfill uses the
site as a referenced source and does not include its prose corpus.
