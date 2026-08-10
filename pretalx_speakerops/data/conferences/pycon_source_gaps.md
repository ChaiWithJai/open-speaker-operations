# PyCon-family historical backfill provenance and gaps

Retrieved and normalized on 2026-08-09, with the legacy PyCon DE recovery
refreshed on 2026-08-10, from first-party conference pages or
official Pretalx exports. `source_updated_at` is the retrieval time because the
static schedules do not expose a per-record modification timestamp. The
committed catalog retains metadata and links, not abstracts or biographies.

## Coverage

- PyCon US: every published talk entry in the official schedules for
  2011–2020 and 2022–2026. PyCon US 2021 was cancelled. This is 15 editions and
  1,452 credited talks.
- PyCon Italia: 2023 (130), 2024 (114), 2025 (124), and 2026 (117), for 485
  credited schedule sessions from the official year sites.
- PyCon DE & PyData: the archived PyCon DE programs for 2011 (54), 2012 (69),
  and 2013 (70), plus 2016 (29), 2017 (54), 2018 (79), 2019 (97), 2022
  (107), 2023 (113), 2024 (118), 2025 (164), and 2026 (140), for 1,094
  credited sessions.
- PyLadiesCon: the complete global-conference run to date: 2023 (41), 2024
  (54), and 2025 (70). The removed 2023 Pretalx feed was recovered from the
  PyLadies-owned `pyladies/global-conference-2023` session CSV.
- DjangoCon US: every recoverable official edition from the inaugural 2008
  event through 2026, excluding cancelled 2020: 2008–2019, 2021–2026, for 706
  credited sessions. The 2008–2009 schedules were recovered from the official
  `djangocon` organization repositories; the 2026 published program was read
  from its official sitemap and talk detail pages.

Total: 52 editions, 3,902 credited talks, and 4,463 speaker credits. Speaker
credits count appearances, so the same person may be represented in several
sessions or editions.

Primary official sources:

- <https://pycon-archive.python.org/2011/schedule/lists/talks/> and
  <https://pycon-archive.python.org/2012/schedule/lists/talks/>
- `https://us.pycon.org/{year}/schedule/talks/` for 2013–2020 and 2022–2026
- <https://pycon.it/en/schedule>
- <https://pycon.de/archive/> and the year-specific PyCon DE sites
- <https://web.archive.org/web/20110809094614id_/http://de.pycon.org/2011/schedule/lists/talks/>
- <https://web.archive.org/web/20121101164923id_/https://2012.de.pycon.org/programm/schedule/>
- <https://web.archive.org/web/20150906080952id_/https://2013.de.pycon.org/programm/zeitplan/>
- <https://2018.pycon.de/schedule/>
- <https://pretalx.com/pyconde-pydata-2025/schedule/export/schedule.json>
  (with equivalent official exports for 2023 and 2024)
- <https://pretalx.com/pyladiescon-2025/schedule/export/schedule.json>
  (and the equivalent 2024 export)
- <https://github.com/pyladies/global-conference-2023/blob/main/generate_site/sessions.csv>
- <https://github.com/djangocon/> and the year-specific DjangoCon US sites
- <https://pretalx.com/djangocon-us-2025/schedule/export/schedule.json>
  (and the equivalent 2023–2024 exports)

## Explicit gaps and exclusions

- PyCon US pages publish a room/time schedule, not a thematic track taxonomy;
  their `track` values are empty rather than inferred. Edition dates and
  locations are also left empty where the talk-list source does not expose
  structured event metadata.
- The official PyCon Italia state provides tags and audience levels, but no
  session track field. Historical subdomains before 2023 no longer resolve or
  expose a centralized official archive; the Python Italia application
  repositories contain no historical schedule fixture.
- The legacy PyCon DE hosts no longer resolve reliably, but preserved snapshots
  of their official schedules provide deterministic title-to-speaker mappings
  for 2011–2013. The live official 2018 schedule is at `2018.pycon.de`, not the
  previously recorded `2018.de.pycon.org` hostname.
- Official PyCon DE history identifies 2014 as a satellite within EuroPython
  2014 and lists no standalone 2015 edition. The EuroPython program is not
  relabelled as PyCon DE. The 2020–2021 archive likewise exposes no completed
  edition catalog.
- Two speakerless PyCon DE 2016 archive cards, two in 2023, five in 2026, one
  PyLadiesCon 2025 organizer block, and four anonymous PyCon US 2025 lightning
  placeholders were excluded because a historical talk requires a credited
  speaker.
- “PyLadies regional” in issue #41 is not a bounded conference series, and the
  official chapter directory has no centralized regional-conference schedule
  archive. The catalog therefore includes every global PyLadiesCon edition but
  does not silently claim every chapter meetup worldwide.
- DjangoCon US 2020 was cancelled. Its preserved schedule page repeats the
  2019 program, so it was not mislabelled and imported as 2020 data.
- These omissions are duplicated in `series.source_policy.known_gaps` inside
  the JSON so automated completeness checks do not depend on this prose file.
- Abstracts and biographies are intentionally empty. Titles, credited speakers,
  formats, tracks when the source publishes them, recording links, source URLs,
  and provenance timestamps are retained.
