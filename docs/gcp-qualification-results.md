# GCP qualification results, 2026-10-14

This campaign demonstrated a fully reconciled 100M-object synthetic history and
one million observed HTTP fault actions. It did not demonstrate 25K accepted
mutations/s, a zero-downtime migration, a million infrastructure crashes or
production readiness. Failed attempts remain retained.

## Environment and ownership

Run `q-20261014092401-2304be` used an isolated VPC/subnet in
`medi-agent-490106`, zone `us-central1-a`. The source host was n1-standard-32
(32 vCPU, 120 GiB RAM, 400 GiB SSD); the separate generator was e2-standard-8
(8 vCPU, 32 GiB RAM, 30 GiB balanced disk). Four application replicas shared
PostgreSQL 16.6, Kafka 3.9.0 with 12 partitions, Redis 7.4.1 and an nginx gateway.
This was one database host and a simulated provider, not a production HA topology.
The API was reachable only inside the run network. Neither VM had a service
account or OAuth scopes. No project SSH metadata, IAM, existing service secrets
or production deployment was changed.

The user authorized a US$25 cap and six-hour limit. Both VMs had an absolute
15:24:02 UTC deletion backstop and auto-delete boot disks. The ownership manifest
checks resource IDs and run markers before deletion. The lifecycle record
contains cleanup time and the before/after identities of the existing
`mediagent-backend` service. Estimated resources cost about US$2/hour plus small
transfer/address charges; this is a sizing estimate, not an observed invoice
or a project-wide billing hard cap.

Application source was built from `aa40ddd`, whose business code matched merged
main `ed36172`. The host tools were subsequently overlaid from `9473d23`; paced
fault tooling came from `6418a7a`, parallel backfill from `c1ac939`, and cutover /
crash drills from `0a3e34c`. The retained provenance records actual OCI image IDs,
source hashes, generator binary hashes, CPU/memory inventory and Go 1.25.3.
Docker 29 required Testcontainers' client API to be set to 1.44. All 34 Java
cases then passed on the cloud host. The compatibility setting is retained in
test resources and also works with the local Docker 28 verifier.

## Historical migration

The historical fixture contains exactly 100,000,000 payment objects, all manual
USD intents in `requires_confirmation`, with deterministic integer amounts and
seed/ordinal metadata. These are database-seeded histories, not 100M HTTP
requests, captures or ledger journals. All constraints, uniqueness, version
guards and durability settings remained enabled.

A 1M pilot measured 49.74 seconds seeding and 105.47 seconds copying. Expansion
from that pilot to 100M took 5,344.12 seconds. The measured source relations used
50,502,098,944 bytes; target relations used 42,096,877,568 bytes. This made the
400 GiB disk adequate without using the developer laptop's storage.

The ordinary service backfill was supplemented with eight checkpointed,
nonoverlapping range workers after its 18.5M history checkpoint. Each range copied
10,187,500 objects, using the same source-first row locking and version-aware
upsert rules. Writes and checkpoint advancement commit together. The ordinary
worker could overlap those ranges safely, so attempted chunk totals must not be
added to derive unique object counts. Full seed/copy/reconciliation finished at
12:41:38 UTC. The full backfill interval was 3,850.43 seconds; the parallel
portion was 1,626.49 seconds, including its final count/handoff.

Both history tables contained 100M objects. Full canonical reconciliation found
zero missing, extra or mismatched rows across 100,414,443 total objects, including
concurrent non-history writes. A subsequent gate reconciliation matched
100,435,618 objects and enabled the read gate. After the infrastructure crashes,
full reconciliation again found zero differences across 100,559,073 objects.
Five boundary history objects were read through a separate 100-percent V2 cohort
in both API contracts. An intentionally corrupted target fell back to source;
the corruption was repaired and source-read rollback passed.

Foreground limits are material. The inline 10/s client accepted all 95,514
attempts but missed 114 scheduled arrivals. The independent 100/s, 30-minute
open-loop stream accepted 179,996 of 180,000 arrivals, with four scheduler drops,
zero unexpected responses, p95 51.57 ms and p99 115.77 ms. It failed the strict
zero-drop gate. A mid-chunk crash/resume of the full 100M campaign was not
performed; checkpoint/version controls have separate local tests. This is a
measured 100M copy/reconciliation and read-cohort demonstration, not full
zero-downtime production migration qualification or a rolling binary upgrade.

## HTTP faults and accounting

The seeded schedule used 4,096 original captures, then mixed concurrent actions:

| Observed action | Count |
| --- | ---: |
| Exact duplicate capture | 697,508 |
| Conflicting request fingerprint | 99,626 |
| Committed response body discarded, then replayed | 202,866 |
| Total successful observed fault actions | 1,000,000 |

The first 4,096 discarded responses were original monetary effects, before any
successful response digest had been learned. Subsequent retries verified stored
response bytes. Seed 42, 128 workers and a 1,000-actions/s pacing ceiling completed
the successful run in 1,000.01 observed seconds, with zero protocol failures.
These counts describe HTTP fault classes. They do not represent one million
worker crashes, provider timeouts, Kafka ambiguities or new payments.

The earlier unpaced million-action run had 51,634 protocol failures and remains
unqualified. Concurrent load and response-discard sockets stressed the generator;
port contention is a hypothesis, not a proven diagnosis. Pacing fixed the observed
protocol failures without changing the accounting or replay checks.

Independent snapshots cover the smoke, failed unpaced and passing paced fixtures:
8,256 succeeded payments, 8,256 capture journals and 16,512 entries, all balanced,
with no duplicate effects or source/target differences. The million successful
actions belong to the paced run alone; results are not combined to invent a pass.

Five separate infrastructure schedules stopped Kafka, observed a committed pending
provider command, stopped Redis and observed a rejected write, then killed one
application instance and PostgreSQL. All 20 observed interruptions recovered
with one provider operation, one balanced settlement and exact confirmation replay
per payment. Recovery intervals were 57.38, 54.24, 9.48, 9.65 and 52.90 seconds.
Three other application replicas stayed available during the application-instance
kills. This is not database failover, off-host recovery or a provider-network test.

## Offered load and delivery gap

All capacity probes create new manual intents with unique idempotency keys.
Replays, HTTP errors and unoffered arrivals are excluded from accepted creates.
The generator records every scheduled ordinal, includes start delay in latency,
and rejects arrivals more than 10 ms late or beyond its concurrency bound.
The unchanged client budgets require zero errors/drops, p95 below 1,000 ms and
p99 below 2,000 ms. The target additionally requires 30 sustained minutes.

| Run | Offered rate / interval | Accepted / drops / unexpected | p95 / p99 ms | Client gate |
| --- | --- | --- | --- | --- |
| cloud-healthy-2000 | 2000/s / 60s | 120,000 / 0 / 0 | 7.27 / 30.06 | Pass |
| cloud-healthy-25000 | 25000/s / 5s | 9,381 / 115,617 / 2 | 2028.61 / 2395.93 | Fail |
| cloud-healthy-5000 | 5000/s / 15s | 66,392 / 8,607 / 1 | 832.83 / 1890.94 | Fail |
| cloud-index-25000 | 25000/s / 5s | 24,892 / 100,108 / 0 | 711.80 / 881.34 | Fail |
| cloud-index-5000 | 5000/s / 15s | 31,970 / 43,030 / 0 | 2876.97 / 3678.10 | Fail |
| cloud-live-backfill-100 | 100/s / 1800s | 179,996 / 4 / 0 | 51.57 / 115.77 | Fail |
| cloud-load-2000-stage | 2000/s / 30s | 60,000 / 0 / 0 | 6.93 / 13.21 | Pass |
| cloud-load-25000-stage | 25000/s / 5s | 30,640 / 94,360 / 0 | 507.64 / 593.27 | Fail |
| cloud-load-500-isolated | 500/s / 30s | 15,000 / 0 / 0 | 6.88 / 7.72 | Pass |
| cloud-load-500 | 500/s / 60s | 17,351 / 8,740 / 3,909 | 1775.93 / 3221.85 | Fail |
| cloud-load-5000-stage | 5000/s / 15s | 73,573 / 1,427 / 0 | 257.37 / 378.68 | Fail |

The initial 500/s probe overlapped the unpaced fault run. The `healthy` probes
ran after copying and crash recovery, while the full post-crash database
reconciliation and delivery recovery could still compete for resources. The
`index` probes used the original application image with an explicitly applied
additive index. These intervals are not equivalent idle-system comparisons.
A short passing 2K/s client run is not 30-minute end-to-end settlement capacity.
The failed 25K preflights prevented a wasteful 30-minute target run.

The cloud exposed a delivery problem: the original claim plan built a hash
anti-join over pending rows and sorted the backlog before its limit. The new
pending-only `created_at` index produced an ordered scan with indexed predecessor
lookups; a retained post-index 100-row observation took about 7 ms. That observation
has a different cache/backlog state from the pre-index scan and is not a controlled
speedup ratio. Concurrent index creation first hit the five-second lock timeout,
leaving an invalid artifact. The invalid index was removed, application replicas
were paused for a recorded maintenance interval, and two stale claim queries were
canceled before the successful retry. No queue events were deleted or marked
published without Kafka acknowledgement.

A later queue burst exposed stale pending-row estimates and a poor inner lookup.
An operator refreshed outbox statistics. The bounded post-overload observation
then ended with zero pending events after 223.24 seconds from its first sample;
the oldest queued work was older than that interval. Final snapshots show 724,737
demo-tenant events and 24,768 fault-tenant events, all published. This is recovery
after operator intervention, not an automatic recovery SLO or a passing overload
latency gate. V4 also lowers the table's automatic analyze eligibility threshold;
that setting is tested with real PostgreSQL locally, and its automatic cadence
was not qualified in this cloud run. Production must monitor pending cardinality,
statistics freshness, query plans, vacuum progress and outbox age under bursty load.

Nine pre-index load runs have exported per-run database counts proving that their
acknowledged creates correspond to distinct committed payments and matching V2
representations. The two failed post-index probes have raw client observations and
the final aggregate drain record, but their run-specific database counts were
omitted by the export filter. They remain failed and cannot establish a database
capacity claim. Do not substitute inferred per-run counts for missing evidence.

## Recompute and reproduce

The sanitized [retained observations](../evidence/gcp/q-20261014092401-2304be/)
include compact HTTP records, summaries, migration chunk timings and foreground
observations, fixtures, accounting snapshots, environment fingerprints, query
plans, cutover/crash records, the ownership lifecycle and SHA-256 checksums.
Two compressed million-action raw files are release assets to avoid adding about
80 MiB to every repository clone. Their compressed sizes/hashes and public URLs
are in `release-assets.json`; both the passing and failed attempts are retained.

```bash
python3 scripts/gcp/validate_campaign.py evidence/gcp/q-20261014092401-2304be
gh release download benchmark-20261014 --repo rajeev-chaurasia/pay-rail \
  --pattern '*.bin.gz' --dir artifacts/cloud-raw
python3 scripts/gcp/validate_campaign.py evidence/gcp/q-20261014092401-2304be \
  --raw-directory artifacts/cloud-raw
```

The second command path recomputes every million-action ordinal, class, observed
HTTP status, replay digest and result from the raw records. The first validates
all locally retained load records, migration foreground counts, reconciliation,
financial snapshots, recovered journal entries and cleanup. Adversarial tests
reject duplicate/truncated raw observations, wrong HTTP statuses, changed digests,
hidden missed arrivals, overlapping ranges, changed balances and unobserved fault
boundaries. Hashes prove file consistency, not independent publisher attestation.
No credentials, private SSH keys, customer data or database dumps are published.

A new run requires explicit cloud authorization and a sized budget. Use
`scripts/gcp/cloud.py` and `remote.py`, the pinned Go generator build, bounded
`migration.py` / `parallel_backfill.py`, and the recorded ownership/topology
contract in [the deployment plan](gcp-qualification-plan.md). The full historical
fixture is intentionally deleted after export. Default CI never provisions paid
cloud resources or automatically repeats a 100M seed.

For the next capacity campaign, isolate foreground APIs, database, delivery
workers and generator resource budgets; instrument scheduler drops separately
from concurrency saturation; tune and test statistics/queue maintenance; measure
new creates, confirmations and settled effects separately. Require fresh full
reconciliation, a bounded automatic drain, and unchanged latency/error budgets
before trying the sustained 25K/s interval. More replicas alone cannot certify it.
