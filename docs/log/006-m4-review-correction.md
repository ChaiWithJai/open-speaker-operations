# Work unit 006: M4 review correction

- **Intent:** Restore the complete Accelevents synchronization journey after
  review identified that the initial contract evidence omitted update APIs.
- **Time box:** Focused review-fix pass on the protected synchronization path.
- **Ran:** Read the newly committed PUT-session and PUT-speaker evidence,
  inspected the stale-preview guard and obsolete preview route, and added
  adapter/mock update support, terminal `4090121` handling, live payload
  validation, and update/no-op tests.
- **Failed:** The previous “no update endpoint” conclusion was wrong. It was
  based on incomplete evidence supplied for M4, not an API limitation.
- **Recovered:** PUT updates now use stored external identities, void-200
  responses are accepted, successful updates refresh fingerprints, and a
  follow-up preview returns `noop`.
- **Abandoned:** The superseded empty `PreviewRun` Accelevents stub was
  removed from the exposed route and dashboard; the historical schedule
  release marker remains for the M1 audit path.
- **What we would do differently:** Capture the entire endpoint family before
  turning a missing page into a fidelity limitation.
