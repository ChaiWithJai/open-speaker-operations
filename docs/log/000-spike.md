# Work unit 000: plugin spike

- **Intent:** Decide whether the competition journey could be delivered by
  extending pretalx rather than forking or rebuilding.
- **Time box:** Early de-risking spike; stop once boot, activation, routing, and
  one rendered surface were proven.
- **Ran:** Inspected pinned pretalx entry points, event activation, URL loading,
  navigation signals, submission signals, schedule release, agenda, widget,
  and ICS source. Booted the plugin and rendered it with Django.
- **Failed:** Python 3.10 could not run pretalx 2025.2.2. `pretalx[test]` was
  not a real extra. The PyPI wheel shipped no upstream test fixtures.
- **Abandoned:** Forking would have made source fixtures and deep hooks easier,
  but it was rejected for upgrade ownership, review size, and licensing
  reasons. `uv` provisioned Python 3.11; `[dev]` and repository factories were
  the working replacements.
- **What we would do differently:** Establish the runtime matrix and fixture
  policy before writing the first feature.
- **Demo relevance:** The spike only counted when the plugin booted and a
  judge-reachable page rendered; source inspection alone was not accepted as
  proof.
