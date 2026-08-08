# Open Speaker Operations

## North star: win with a demoable journey

The goal is to win the competition by rapidly prototyping a fully working,
demoable speaker/program-management solution aligned to the original
competition documentation, then iterating until a judge can complete the seeded
journey. The process is part of the deliverable: decisions, failures, decay,
and recovery stay visible through git history, logs, tests, and the context
graph.

**Subordination rule:** demoable journey first. Anything not reachable in the
seeded judge journey does not count as complete, no matter how elegant the
architecture is. The protected path is:

```text
CFP → review → acceptance → onboarding → conflict-aware release
→ public output → synchronization proof
```

Open-source planning and implementation baseline for replacing the
speaker/program-management subset of Sessionboard described in the AIE “Kill
My SaaS” competition.

## Architecture

Extend pretalx as a disclosed, license-compliant modular monolith. Use Rails 8 only if competition rules prohibit derivative work. Deploy the application and worker to DigitalOcean with PostgreSQL as authority, Cloudflare R2 for objects, and Cloudflare at the edge.

## Documents

- [Product requirements](./kill-my-saas-prd.md)
- [Architecture RFC](./rails-monolith-rfc.md)
- [Implementation plan](./speaker-operations-implementation-plan.md)
- [Context graph](./docs/context-graph.md)
- [Working log](./docs/log/)
- [Auditable seam decisions](./docs/decisions/)

## Requirements authority

The [canonical competition document](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/mobilebasic) remains the source of truth for competition requirements. Repository issues provide traceability from those requirements to product, architecture, and implementation decisions.

## Evidence policy

DeepWiki is used for architectural navigation. Every implementation-critical claim must be verified against the exact pinned upstream source and tests because DeepWiki may lag the current repository revision.

## License

AGPL-3.0. Any future pretalx-derived implementation must also preserve and satisfy the applicable upstream license, notices, attribution, and modification-identification requirements.
