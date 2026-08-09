# GDC and GOTO historical backfill evidence

Collected 2026-08-09. The JSON files contain factual catalog metadata only: titles, source-published presenter credits, formats or media types, tracks, recording links, and provenance. Abstract and biography prose is intentionally not republished.

## Coverage

| Series | Editions | Talks | Speaker credits | Distinct source names |
| --- | ---: | ---: | ---: | ---: |
| GDC | 40 | 10,200 | 10,953 | 7,142 |
| GOTO | 34 | 1,258 | 1,439 | 849 |
| Combined | 74 | 11,458 | 12,392 | 7,971 per-series sum before cross-series identity normalization |

The contracted full-corpus verification report is the authoritative database
count. The source documents contain 74 editions, 11,458 talks, and 12,392
source credits across these two series.

## GDC

Sources:

- Public historical compilation, updated 2024-11-23: <https://www.retroreversing.com/gdc>
- Official GDC Vault browse catalogs for every year 2005–2025: <https://www.gdcvault.com/>
- Official 2026 agenda: <https://schedule.gdconf.com/sessions>
- Official robots policies allowed collection: <https://www.gdcvault.com/robots.txt> and <https://schedule.gdconf.com/robots.txt>

Coverage by source:

- 1988–2004: 18 editions and 1,532 speaker-backed rows from the public historical compilation. It explicitly describes several early years as incomplete. Fifty-two rows without usable presenter credits were excluded. Twenty-eight titles remain truncated exactly as the compilation publishes them.
- 2005–2025: all 21 official Vault browse catalogs, comprising 13,264 media rows. After excluding 20 rows without presenter credits and collapsing 5,194 duplicate video/audio/slide assets for the same title and presenter, the dataset contains 8,050 distinct talks. All 3,173 truncated browse-card titles were resolved through the official link title or official detail-page metadata.
- 2026: all 695 entries from all 28 official agenda pages. The dataset contains 618 speaker-backed talks. Seventy-four non-talk program items without speaker credits were excluded. Three talk-like entries without published speaker credits were also excluded: sessions 917364, 917365, and 918300.

Metadata gaps:

- The 2005–2025 Vault exposes media type and track, not original stage format. `session_format` therefore records `Vault video`, `Vault audio`, `Vault slides`, or the source's archive media type.
- The historical compilation does not publish format for 1,022 imported rows or track for 916 imported rows. Empty values are preserved for importer normalization; none are guessed.
- The 2026 agenda omits format for 34 speaker-backed sessions.
- Presenter strings from the public historical compilation are retained verbatim when the source is ambiguous rather than heuristically splitting surnames.

## GOTO

Sources:

- Official catalog and session pages: <https://gotopia.tech/sessions>
- Official event archive: <https://gotopia.tech/events/past>
- Official GOTO Amsterdam 2015 schedule: <https://gotocon.com/amsterdam-2015/schedule/>
- Official GOTO Amsterdam 2016 schedule: <https://gotocon.com/amsterdam-2016/schedule/>
- Official robots policy: <https://gotopia.tech/robots.txt>

Coverage:

- 2015–2016 Amsterdam schedules: 141 published program rows inspected; 130 speaker-backed presentations or trainings imported and 11 introductions/social events without speaker credits excluded.
- GOTO/GOTOpia city catalogs: 32 discoverable Amsterdam, Berlin, Chicago, Copenhagen, and London editions, including Chicago and London city-branded variants and the named 2026 editions. The official pages expose 1,103 session records; 1,101 speaker-backed records were imported.
- The current official Copenhagen 2026 masterclass catalog contributes 25
  credited masterclasses. The event is future and its main-session schedule is
  not yet published.
- The current official Accelerate Chicago 2026 masterclass catalog contributes
  both credited masterclasses. The held event's complete main-session program
  is not exposed by its current official schedule route.
- Two official session records have no author credit and were excluded: session 664, “Meet the Legends of Software,” and session 2011, “Thinking Serverless: From User Request to Serverless Solution.”
- Five official held-edition pages currently expose no public session catalog:
  Amsterdam 2020, Berlin 2020, Copenhagen 2020, London 2022, and GOTO
  Community Day Chicago 2023. Copenhagen and Chicago 2026 are no longer empty,
  but remain explicitly partial as described above.

Metadata gaps:

- The modern official archive publishes the material as `VideoObject` records and retains related topics, but not original stage format or track. `Recorded session` is the source-backed media format; track remains empty for those 1,101 records.
- Nine speaker-backed Amsterdam 2015–2016 keynote rows and the 27 newly
  recovered masterclasses publish no track. Across GOTO, 1,137 talks therefore
  have no source-published track.

## Validation

- Both JSON documents parse successfully and contain unique edition keys and unique talk keys within each edition.
- Every imported talk has a title, HTTPS source URL, source timestamp, and at least one source-backed speaker credit.
- Every edition has an HTTPS source URL and source timestamp.
- No abstract or biography fields are present.
- Each `series.source_policy.known_gaps` array contains machine-auditable scope, item, reason, and source URL records for irreducible omissions.
- `tests/test_conference_memory.py`: 21 passed after field-level provenance coverage was added.
- The immutable full-corpus contract and exact database verifier replace the
  earlier isolated-import count notes; they must pass after every refresh.
