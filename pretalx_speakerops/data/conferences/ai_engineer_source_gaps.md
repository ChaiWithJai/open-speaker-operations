# AI Engineer historical backfill provenance and gaps

Retrieved and normalized on 2026-08-09. `source_updated_at` is the upstream
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
| AI Engineer NYC 2026 | 0 | <https://www.ai.engineer/nyc/2026> |
| AI Engineer World's Fair 2027 | 0 | <https://www.ai.engineer/worldsfair/2027> |

Total: 7 editions, 705 credited sessions, and 846 speaker credits.

## Explicit gaps and exclusions

- NYC 2026 and World's Fair 2027 are announced editions, but their official
  pages do not publish a speaker program as of retrieval. They remain edition
  records with zero talks; no agenda was synthesized.
- Forty-four speakerless schedule blocks were excluded: 10 from Summit 2023,
  24 from World's Fair 2024, and 10 from Code Summit 2025. They are
  registration, food, expo, break, reception, or afterparty blocks rather than
  credited talks.
- The World's Fair 2025 dump leaves 45 session formats and 139 tracks blank,
  and Europe 2026 leaves 44 tracks blank. Those values remain empty rather
  than being inferred from titles or rooms. Summit 2023 is different: its
  official schedule explicitly says all talks use a single track, so all 53
  records are enriched as `Single track` with field-level source provenance.
- The issue text lists World's Fair 2025 as June 25–27. The official 2025
  schedule says June 3–5, so the dataset follows the first-party schedule.
- Abstracts and biographies are intentionally empty. Titles, credited speakers,
  formats, tracks, recording links, source URLs, and provenance timestamps are
  retained.

The AI Engineer robots policy allowed general access when retrieved and stated
`Content-Signal: search=yes,ai-train=no,use=reference`; this backfill uses the
site as a referenced source and does not include its prose corpus.
