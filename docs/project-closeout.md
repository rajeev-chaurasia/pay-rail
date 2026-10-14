# PayRail project closeout

Reference implementation delivery and the bounded qualification campaign are
complete as of 2026-10-14. The supported product is a simulated payment platform
with a same-origin playground, reproducible Docker verification and retained
measured evidence. It does not process card data or move real funds.

## Delivered and verified

| Deliverable | Verification and evidence |
| --- | --- |
| Authenticated payment lifecycle and tenant isolation | Create/get/list/confirm/capture/cancel/refund, invalid input, authorization and failure paths in [flow coverage](testing.md) |
| Fingerprint idempotency and versioned responses | Concurrent key races, conflicts and saved-byte replay in [evidence](evidence.md) |
| Immutable double-entry accounting | PostgreSQL commit constraints, unique effect keys and independent journal checks |
| Transactional outbox and simulated provider | Fenced leases, redelivery, accepted response loss, bounded retries and acknowledged quarantine |
| Live playground and architecture | README screenshot, colored Mermaid diagram and [playground walkthrough](playground.md) |
| Migration controls | Additive representation, dual writes, checkpointed copying, reconciliation, gated read cohort and source fallback |
| 100M synthetic histories | Full source/target counts and zero canonical differences in [GCP results](gcp-qualification-results.md) |
| One million observed HTTP fault actions | Three explicit classes, retained failing attempt, raw release assets and independent accounting |
| Crash and restore mechanisms | Five cloud schedules plus isolated Docker crash, logical restore and [physical backup/WAL recovery](postgres-recovery.md) |
| Reproducible verification | 34 Java, one currency and 20 Python cases; formatting, package, evidence, Go vet and Compose checks |
| Delivery automation | GitHub CI also scans the runtime and runs isolated backup/recovery drills |

The README links directly to measured successes, failed targets, workload/hardware
scope, raw observations, downloads, checksums and reproduction instructions.
Historical local studies remain available, including failures.

## Cleanup and handoff

Both temporary GCP VMs, their auto-delete disks, custom firewalls, subnet and VPC
were deleted on 2026-10-14 at 07:05 Pacific time, before the approved six-hour
backstop. The ownership lifecycle records matching existing Mediagent service
identity/revision before and after cleanup. No production configuration was
changed. Private test credentials are not published with the evidence.

The local `payrail` Docker project remains available for demonstration at
`http://localhost:18080/`. Its database is preserved. Other local Docker projects
are outside this project's cleanup scope. Use `./scripts/dev-down.sh` when the
demonstration is no longer needed; it preserves the PostgreSQL volume.

Final source and documentation are delivered through reviewed GitHub pull
requests. Check the latest main-branch CI result before using a fresh checkout.
No paid cloud campaign is automatically scheduled or run by CI.

## Future qualification boundaries

These are separate future work, not completed capabilities:

- Sustained 25K accepted mutations/s and end-to-end settlement capacity. The
  bounded 25K probes failed; the measured 2K/s create-only run lasted 60 seconds.
- Zero-downtime production migration. The 30-minute foreground stream dropped
  four arrivals; the inline stream missed 114. Full-scale mid-chunk crash/resume
  and rolling mixed binaries were not qualified.
- Automatic overload recovery SLOs. The cloud outbox required index/statistics
  intervention; actual automatic analyzer/vacuum cadence still needs a campaign.
- A broad million-fault infrastructure/provider campaign. The successful million
  covers duplicate captures, fingerprint conflicts and discarded committed
  bodies. Twenty infrastructure interruptions were observed separately.
- Real provider reconciliation, production HA/failover, off-host backup durability,
  RPO/RTO, deployed transport/IAM controls, RLS defense in depth and operator approval.

The [production gates](production-readiness.md) and [known limits](known-misses.md)
retain those boundaries. Production readiness is not claimed by this closeout.
Any further paid deployment or full qualification campaign needs a new scope,
authorized environment and budget.
