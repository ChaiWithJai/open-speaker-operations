# Work unit 004: context graph and visible process

- **Intent:** Make “demoable” the repository's north star and turn every
  acceptance claim into a checkable requirement-to-demo chain.
- **Time box:** Backfill after M3; no new product surface was allowed to
  preempt the protected journey.
- **Ran:** Added the north star to the root and decision docs, created the
  machine-readable context graph and rendered view, added a P0 proof gate and
  GitHub workflow, and backfilled spike/M0/M1/M2/M3 logs.
- **Failed:** No existing CI workflow or process log existed to extend.
- **Abandoned:** A graph that silently omitted unfinished P0 work was rejected;
  explicit `gaps` remain visible with shortest paths. A meta-layer-first build
  was avoided because it would describe work before the journey existed.
- **What we would do differently:** Start the graph at M0 and update it in each
  milestone commit.
- **Doom-loop:** Not invoked in this unit; no protected-path blocker exceeded
  the time box.
