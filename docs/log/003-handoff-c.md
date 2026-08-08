# Work unit 003: M3 program and publication

- **Intent:** Make the seeded conflict visible, block unsafe release, then
  expose only the released schedule through ICS and an embed.
- **Time box:** M3 plus the blocking decision-record review fix.
- **Ran:** Inspected review, warning, freeze, widget, and ICS source; added
  review configuration, warning policy, ICS identity/sequence/cancellation,
  released embed, seed release lifecycle, and records 008–010.
- **Failed:** ICS `SEQUENCE` initially serialized as an integer; the test
  expected bytes while the exporter returned text. The first seed replay tried
  to publish the same schedule version, and unrelated generated conflicts
  remained after resolving the deliberately seeded pair.
- **Abandoned:** Reimplementing the schedule conflict engine and ICS formatter
  was cut in favor of pretalx services plus a narrow plugin policy/identity
  layer. The seed now resolves all blocking warnings for release and recreates
  deliberate conflicts on WIP afterward.
- **What we would do differently:** Inspect the exact exporter return type and
  freeze idempotency before writing the first assertion.
- **Demo relevance:** Release failure and successful release are both exercised
  in seed setup; current WIP conflicts remain judge-visible while the released
  public schedule is clean.
