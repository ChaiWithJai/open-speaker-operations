# JSConf and Strange Loop historical source notes

Retrieved 2026-08-09. The JSON files beside this note contain only factual
program metadata (edition, title, speaker, format/section, track/room, recording
URL, and source provenance). Abstract and biography prose is deliberately not
republished.

## Strange Loop

- Official source: <https://www.thestrangeloop.com/schedule.html> and each
  edition/session page linked from it.
- Coverage: every edition exposed by the official archive: 2009–2019 and
  2021–2023 (14 editions, 1,049 speaker-attributed session records). There was no archived 2020
  edition in the official index.
- The archive lists 2009–2023 session cards under program section headings.
  Those headings are retained as `track`; they may be program categories rather
  than physical rooms.
- Exact event dates are not exposed by the edition session indexes, so date
  fields remain empty. Parties, board-game night, and the PWLConf/Elm-conf
  preconference links were removed because they are not speaker-attributed
  Strange Loop sessions. The 2022 "It Will Never Work in Theory" embedded
  mini-conference is retained with all eight researchers named on its official
  session page.
- `robots.txt` returns an S3 AccessDenied response. The public archive pages were
  fetched slowly and without crawling any unlinked paths.

## JSConf JP

- Official source and reproducible record: <https://github.com/jsconfjp/jsconf.jp>.
- Coverage: every speaker-attributed program stored in the current official
  repository: 2019, 2021, 2022, 2023, 2024, and 2025 (212 talk records). No 2020 event data is
  present. The repository starts at 2019.
- Forty schedule-furniture records (open/close, breaks, and parties) were
  removed. Six genuine rows were recovered from first-party titles that name
  their presenters: the 2021 opening, Wantedly, Recruit, Hey, and Twilio talks,
  and the 2022 opening.
- Thirty-seven genuine sponsor/workshop rows remain omitted because the
  first-party data identifies only an organization or composite block, not an
  individual speaker. Their exact external keys are:
  - JP 2019: `sponsor-talk-1`, `sponsor-talk-2`.
  - JP 2021: `sponsor-talk-kaonavi`, `sponsor-talk-nota`,
    `reflections-on-the-introduction-of-graph-ql-and-a-new-challenge`,
    `kaonavi-js-conf-jp-2021-sponsor-lt`,
    `frontend-development-for-ubie-discovery-creating-value-simultaneously-and-multiply`,
    `how-to-use-type-script-in-study-supplement-and-its-future-prospects`,
    `front-end-technology-supporting-stores-reservation`,
    `legal-force-s-front-end-development-past-and-future`,
    `js-conf-jp-2021-sponsor-lt-nota`, and
    `js-conf-jp-2021-sponsor-lt-twilio`.
  - JP 2022: `sponsor-talk-miidas`, `sponsor-talk-nota`,
    `sponsor-talk-dwango`, `sponsor-talk-kaonavi`, `sponsor-talk-twillio`,
    `sponsor-talk-cybozu`, `sponsor-talk-wantedly`,
    `miidas-js-conf-jp-2022-sponsor-lt`,
    `nota-js-conf-jp-2022-sponsor-lt`,
    `dwango-js-conf-jp-2022-sponsor-lt`,
    `kaonavi-js-conf-jp-2022-sponsor-lt`,
    `twilio-js-conf-jp-2022-sponsor-lt`,
    `cybozu-js-conf-jp-2022-sponsor-lt`, and
    `wantedly-js-conf-jp-2022-sponsor-lt`.
  - JP 2023: `workshop-helpfeel`.
  - JP 2024: `day1-`, `miidas`, `earthbrain`, `mercari`, `hireroo`,
    `lycorp`, `ivry`, `helpfeel`, `layerx`, and `medley`.
  These can be restored only when the organizer supplies speaker attribution;
  using the sponsor organization as a person would corrupt the memory model.
- Physical track/room labels are retained where present.
- Exact dates for all six editions are normalized from the official repository's
  localized event-date strings.

## JSConf EU

- Official source and reproducible record: repositories owned by the JSConf
  organization at <https://github.com/orgs/jsconf/repositories>, plus the
  corresponding official edition sites.
- Coverage: 2009–2015 and 2017–2019 (10 editions, 449 talk records). The 2009
  official speaker archive supplied 26 title/speaker records after its schedule
  was retired; official archived program posts supplied 42 records for 2010 and
  34 speaker-attributed records for 2011. The official history has no 2016
  edition, so none was added by inference.
- The 2009 archive no longer exposes schedule slots or tracks. Two 2011 rows
  (`Audio Jedi` and `Surprise talks`) remain omitted because the official page
  supplies no individual speaker attribution. These exceptions are also
  recorded in `source_policy.known_gaps`.
- Organizer-published schedule data supplied 239 exact-title track enrichments
  across 2013, 2014, 2015, 2017, and 2018. Every enriched field retains its
  schedule URL and retrieval timestamp. Eleven unmatched/ambiguous rows were
  left blank; no fuzzy title assignment was used.

## JSConf US

- Official source: edition sites and repositories owned by
  <https://github.com/jsconf>.
- Coverage with recoverable schedules: 2010, 2013, 2014, 2015, Last Call 2015,
  2018, and 2019 (263 talk records). Curated and community track labels are
  retained from the schedules.
- The official 2009 schedule page intentionally contains no schedule (its body
  says "Loading..." followed by a joke); the edition is represented with zero
  talks and its exact source URL.
- The official 2011 and 2012 sites did not return usable pages, and their
  first-party GitHub repositories contain only README pointers. These editions
  are represented with zero talks so the absence is queryable, not hidden.
- "Open Slot", breaks, meals, and other non-talk schedule rows are excluded.

## JSConf Iceland

- Official source and reproducible record: <https://github.com/jsis/jsconf.is>,
  including its `2016` tag and current 2018 data.
- Coverage: 2016 and 2018 (61 talk records). The source does not assign a room to
  every speaker record, so track is empty rather than guessed.
- No official 2017 edition or program record was found between the repository's
  2016 and 2018 editions; that absence is machine-readable in `known_gaps`.

## JSConf China

- Official source: <https://jsconf.cn/>. Its edition index identifies 2012,
  2013, 2014, 2015, 2016, 2017, and 2019 with locations and dates.
- Recoverable official Internet Archive snapshots and the archived 2016 site
  bundle provide 18 speaker-attributed records for 2016, 14 for 2017, and 17
  for 2019 (49 total). Lighting talks, panels, recruiting rows, and one
  organization-only workshop are omitted rather than assigned invented people.
- The 2012–2015 event records remain edition-only: their retired program
  endpoints were unavailable and the archive rate-limited the bounded recovery
  pass. Each remaining program gap is recorded in `source_policy.known_gaps`.
  The official index does not list a 2018 event, so none is invented.

## JSConf BR / BrazilJS

- Official JSConf BR archival redirects and the first-party BrazilJS historical
  archive establish the continuation of this regional lineage. Coverage is
  2011–2021 and 2024 (12 edition records, 172 speaker-attributed talks).
- 2018, 2020, 2021, and 2024 remain edition-only because the official pages do
  not expose deterministic title-to-speaker mappings. Three title-less 2015
  keynotes are omitted. The official 2025 announcement is documented as a gap,
  not represented as a held event.
- The two-city 2017 program repeats 21 talks in Porto Alegre and Fortaleza;
  location-qualified external keys preserve both appearances without identity
  collisions.

## JSConf Uruguay

- Official archived schedules cover 2014–2016 (3 editions, 76 talks). Three
  speaker-attributed 2014 placeholders whose title is only “to be announced”
  are omitted and recorded in `known_gaps`.

## JSConf Belgium

- Official archived edition pages cover 2014–2019 (6 editions, 60
  speaker-attributed talks).
- Ten 2015 schedule titles cannot be linked deterministically to the separately
  listed speaker roster, and the 2018 schedule snapshot is unavailable. These
  remain explicit machine-readable gaps rather than guessed pairings.
