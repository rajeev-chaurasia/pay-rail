# Temporary GCP qualification plan

Status: initial deployment authorized, 2026-10-14, with a US$25 total spend cap
and six-hour limit. No cloud resources have been created at preparation time.

## Scope and isolation

Project: `medi-agent-490106`. Read-only inventory found the existing
`mediagent-backend` Cloud Run service in `us-central1`, a default VPC, no Compute
Engine instances/disks and no GKE clusters. Cloud SQL Admin is disabled; this
campaign will not enable it. Inventory must be refreshed before provisioning.

All new resources use one unique `payrail-qual-*` run prefix and ownership labels.
Use a new custom VPC and subnet with no peering to the default network. SSH is
allowed only through IAP to tagged benchmark VMs; application ingress is allowed
only from the dedicated generator's internal address. PostgreSQL, Redis and Kafka
stay inside the benchmark host's Docker network. No public application endpoint.

The campaign changes no existing service, database, secret, IAM binding, project
SSH metadata, DNS, default firewall or project configuration. VMs have no attached
service account; temporary public SSH keys belong only to their instance
metadata. Private keys stay in ignored local artifacts and are never published.
Shared project quota consumption is recorded and kept below current limits.

The initial generator stores one 24-byte binary record per offered arrival,
including dropped work, rather than a full stream of per-request JSON metrics.
Independent validation checks arrival identities, accepted/rejected outcomes and
latency including scheduled-arrival delay. Generator startup and scheduling
drops remain failures. At 25K arrivals/s for 30 minutes, the raw attempt file is
about 1.08 GB before compression; database, drain and reconciliation observations
are additional required evidence.

## Initial resources and estimated cost

Region: `us-central1`; select an available zone after quota/capacity checks.

| Resource | Proposed size | Indicative hourly cost |
| --- | --- | --- |
| Benchmark host | `n1-standard-32`, 32 vCPUs, 120 GiB RAM | US$1.52 |
| Separate load generator | `e2-standard-8`, 8 vCPUs, 32 GiB RAM | US$0.27 |
| Benchmark boot/data disk | 400 GiB SSD Persistent Disk, auto-delete | US$0.093 |
| Generator boot disk | 30 GiB balanced Persistent Disk, auto-delete | US$0.004 |
| Ephemeral external addresses | Outbound installation/download access | Allowance required |

Planning allowance: US$2-3/hour before taxes and evidence-transfer charges.
Recommended initial total spend limit: US$25. This is an estimate, not a billing
guarantee. No discounted commitments or Spot/preemptible capacity are assumed.
Rates must be rechecked at provisioning. The 400 GiB SSD request leaves 100 GiB
of the currently unused 500 GiB regional SSD quota. CPU quotas have headroom for
the proposed hosts. Future project activity can change that headroom.

Sources: Google's [general-purpose VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose)
and [disk pricing](https://cloud.google.com/compute/disks-image-pricing).

## Execution and acceptance

1. Finish and locally check the campaign harness before starting billable VMs.
2. Capture a baseline of existing resource identities and Cloud Run revision;
   write the exact new resource identities to a local ownership manifest.
3. Bootstrap Docker, pin source revision and image identities, run correctness
   and recovery checks, then measure a small storage/seed/migration pilot.
4. Use the pilot to estimate full runtime and storage. Do not start a 100M seed
   unless measured capacity and remaining time fit the declared headroom.
5. Seed historical synthetic payment objects in bounded resumable transactions.
   Measure backfill with foreground traffic, interruption/resume, full
   reconciliation, gated cutover and rollback. Report source objects separately
   from total rows. Historical seeding is separate from HTTP-created throughput.
6. Use the separate generator for staged offered rates. A 25K/s qualification
   requires 30 sustained minutes, accepted mutations reported separately from
   replays/rejections, declared latency/error budgets and bounded outbox drain.
   Retain failures; a larger machine does not guarantee the target will pass.
7. Run a seeded fault schedule with observed injection boundaries, per-class
   counts and reconciliation. One million counted faults cannot be replaced by
   one million requests or repeated assertions. Retain raw sanitized traces.
8. Export reports, compressed raw observations, source/environment fingerprints
   and checksums locally before cleanup. Independently validate the evidence.
9. Delete only the exact run-owned resources from the manifest, checking ownership
   before each deletion. Verify no run-owned VM, disk, address, firewall, subnet
   or network remains; compare existing resource identities with the baseline.

## Runtime and cleanup bounds

One hour is not promised: the sustained throughput interval alone is 30 minutes,
and full seeding, migration, reconciliation, setup and fault runs take additional
time. The initial hosts have a six-hour maximum runtime with automatic deletion
and auto-delete disks. Export intermediate evidence regularly and stop new tests
before that deadline so cleanup cannot erase the only copy of results.

Use a [Compute Engine maximum-runtime termination policy](https://docs.cloud.google.com/compute/docs/instances/limit-vm-runtime)
as a backstop. Explicit cleanup remains required for firewall/subnet/VPC resources
and interrupted provisioning. A runtime limit is not a GCP billing hard cap;
resource/transfer estimates and a contingency margin control planned exposure.
Any larger host, longer runtime or spend-limit increase requires a new decision.

This deployment is a synthetic qualification environment. It does not process
real funds or certify production readiness merely by running in GCP.
