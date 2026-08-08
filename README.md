# Open Speaker Operations

Open-source planning and implementation baseline for replacing the speaker and program-management subset of Sessionboard described in the AIE “Kill My SaaS” competition.

## Decision

Extend pretalx as a disclosed, license-compliant modular monolith. Use Rails 8 only if competition rules prohibit derivative work. Deploy the application and worker to DigitalOcean with PostgreSQL as authority, Cloudflare R2 for objects, and Cloudflare at the edge.

## Documents

- [Product requirements](./kill-my-saas-prd.md)
- [Architecture RFC](./rails-monolith-rfc.md)
- [Implementation plan](./speaker-operations-implementation-plan.md)

## Requirements authority

The [canonical competition document](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/mobilebasic) remains the source of truth for competition requirements. Repository issues provide traceability from those requirements to product, architecture, and implementation decisions.

## Evidence policy

DeepWiki is used for architectural navigation. Every implementation-critical claim must be verified against the exact pinned upstream source and tests because DeepWiki may lag the current repository revision.

## License

AGPL-3.0. Any future pretalx-derived implementation must also preserve and satisfy the applicable upstream license, notices, attribution, and modification-identification requirements.
