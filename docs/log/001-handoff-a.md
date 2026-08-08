# Work unit 001: M0/M1 golden skeleton

- **Intent:** Reach the protected CFP → review → acceptance → onboarding →
  release → public output → preview path with a one-command seed.
- **Time box:** M0/M1 handoff, keeping the implementation thin enough for a
  judgeable golden path.
- **Ran:** Built the plugin entry point, domain executor, acceptance receiver,
  dashboard, checklist, preview stub, seed command, local factories, and
  golden-path pytest.
- **Failed:** Initial route choices collided with pretalx's speaker route;
  direct environment Python and missing wheel fixtures blocked the first test
  plan.
- **Abandoned:** A fork and upstream fixture dependency were dropped in favor
  of plugin-owned factories and a non-colliding event URL.
- **What we would do differently:** Put role-denial tests and explicit conflict
  fixtures in the first skeleton instead of adding them after review.
- **Demo relevance:** The seeded journey and the exact client-level test were
  the completion criterion; architecture not on that path was deferred.
