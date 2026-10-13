# Contributor convention sources

PayRail adopts shared conventions from the owner's projects and translates
language-specific tooling to Java. Source projects are references, not runtime
dependencies.

| Source | Applied convention | PayRail implementation |
| --- | --- | --- |
| [MediAgent contributor contract](https://github.com/sjsu-masters-projects/medi-agent/blob/main/AGENTS.md) and locally available project docs | Canonical instructions, task routing, thin controllers, scoped services, tracked acceptance, review evidence | `AGENTS.md`, `.agent/`, `CONTRIBUTING.md`, PR template |
| [Acquit contributing](https://github.com/rajeev-chaurasia/acquit/blob/main/CONTRIBUTING.md) | Enforced formatting and prose, deterministic results, adversarial tests | Pinned Java formatter, style gate, evidence validation |
| [Leak-proof contributing](https://github.com/rajeev-chaurasia/leak-proof/blob/main/CONTRIBUTING.md) | No authoring-tool attribution, no em dashes, claim only implemented checks | Style gate, synthetic defaults, measured-versus-target documentation |
| [Webhook-ledger evidence](https://github.com/rajeev-chaurasia/webhook-ledger/blob/main/docs/evidence.md) | Genuine concurrent overlap, broken control, raw intervals and independent validator | Isolated PostgreSQL race evidence and CI validation |
| [Benchgrid evidence](https://github.com/rajeev-chaurasia/benchgrid/blob/main/docs/evidence.md) | Provenance, checksums, independently recomputed results and explicit limits | Evidence manifest, validator and method documentation |
| [RocketRide contributor contract](https://github.com/rajeev-chaurasia/rocketride-server/blob/main/AGENTS.md) | One instruction source, conventional commits, contract docs in the same change | Root contract and contributor workflow |

The MediAgent source was read locally from its `AGENTS.md`, `CONTRIBUTING.md`
and `.agent/CODING_STANDARDS.md` and `TEAM.md`. Its clinical data, localization,
Supabase and staffing rules do not apply to a payments reference service.
Python, Ruby, TypeScript and C++ commands are replaced by Java-appropriate gates.
RocketRide's develop branch workflow is repository-specific; PayRail uses main.
Older unsupported readiness claims are not copied from other project READMEs.

Formatting uses a pinned Java formatter. The small-method and small-signature
preference is documented with explicit Java framework/record exceptions.
Remote protection, peer approval and release remain maintainer actions; local
files alone do not assert those settings are active.
