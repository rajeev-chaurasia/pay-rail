# Local performance method and results

The measurements use k6 1.3.0 from a pinned official Docker image. The runner
starts an additional application and dedicated Redis instance, creates a fresh
synthetic tenant and disables its API key afterward. It never resets the demo
schema or stops unrelated services. Load generation, both application instances,
PostgreSQL and Kafka share the development machine and Docker VM. The VM exposes
10 CPUs and about 7.65 GiB of memory; other workloads can compete for those
resources. This is a local experiment, not isolated hardware qualification.

The benchmark application uses a 20-connection database pool, a 128..512 MiB
JVM heap, a 1,000,000 requests/minute admission ceiling, dual writes, and 100%
shadow/V2 read cohorts subject to the existing clean cutover gate. The original
app supplies one outbox dispatcher; older artifacts used serial publication,
while the production-hardening revision uses bounded independent-head batches; both instances join the provider
consumer group. Manifests record image identities, source hashes, dirty-tree
status, configuration and versions. No result is extrapolated to 25K/s.

## Workloads and predeclared budgets

- Smoke: 10 new manual intents/s for 15 seconds.
- Sustained repeats: 100 new manual intents/s for 60 seconds, twice.
- Stress: 200/s for 20 seconds, transition to 400/s for 20 seconds, then 800/s
  for 20 seconds. The run aborts after an unexpected response is observed.
- Mixed: 10 workflows/s for 60 seconds. Workflows cover automatic or manual
  capture followed by partial/full refund, or cancellation before/after manual
  authorization. They also exercise exact replay, fingerprint conflict,
  forbidden transitions and both response contracts.
- Lower baselines: 25 new manual intents/s for 60 seconds, twice, and a lower
  mixed-workflow rate to establish a passing observed operating range.

Arrival executors schedule work independently of response completion. Dropped
iterations are retained and fail the budget. A workflow can include many HTTP
requests, so workflow arrivals and HTTP requests/s are separate measurements.
Expected 409 conflicts do not count as infrastructure failures. A replay that
returns 200/201 is an accepted HTTP response, not a new monetary effect.

Budgets declared before load: no unexpected status, failed semantic check,
rate-limit rejection or dropped iteration; aggregate p95 below 1,000 ms and p99
below 2,000 ms; all started workflows complete; outbox and processing drain
within five minutes; no unexplained accounting or migration mismatch. Raw
per-operation latencies are also reported. An expected schedule can differ by
one boundary iteration due to the arrival executor's endpoint timing.

## Reproduction

Start the local stack and package current sources before testing:

```sh
./scripts/dev-up.sh
python3 scripts/performance/run.py
python3 scripts/performance/validate.py --allow-unqualified
```

The Docker-backed runner takes several minutes and requires access to the
existing local stack. Single-profile examples:

```sh
./scripts/benchmark.sh --profile quick --rate 10 --duration 30s
python3 scripts/performance/run.py --profiles baseline-a,baseline-b,mixed-baseline
```

Only dedicated benchmark containers are removed. Synthetic rows remain for
inspection; credentials are disabled. The `--rate` and `--duration` overrides
require one non-stress profile and have explicit local bounds. Separately sized
qualification must use its own resource plan and harness.

## Evidence contract

Each run retains:

- `manifest.json`: declared workload, budgets, source/image identity and topology.
- `raw.json.gz`: every k6 metric observation, including request name/status and
  duration, semantic checks, starts/completions and dropped iterations.
- `summary.json`: producer summary; k6's trailing newline is normalized before
  sealing without changing its JSON values.
- `snapshot.json.gz`: one consistent tenant-scoped PostgreSQL statement captures
  payments, journal headers/entries, refunds, events, provider operations and V2.
- `drain.json`: post-load backlog observations up to the declared deadline.
- `resources.jsonl`: sampled container CPU/memory and generator observations.
- `migration.json` on mixed runs: concurrent administrative backfill requests.
- `checksums.json` and `report.json`: byte checksums and recomputed results.

The independent validator recomputes percentiles and counters from raw points,
compares the producer summary, verifies committed counts against started and
acknowledged work, and checks journal balances/directions/business keys, refund
bounds, provider uniqueness, event sequences and full migration representations.
It rejects altered monetary observations even when capacity failures are allowed.
Checksums provide consistency, not proof that an untrusted publisher executed
an experiment. The recorded source hashes identify the run's source snapshot;
older results are not claimed to describe later modified source.

## Interpretation and misses

Manual-create throughput measures admission and persistence, not end-to-end
settlement. HTTP latency measures completed responses; dropped and interrupted
work must be read alongside it. A committed create without an acknowledgement
is counted as an uncertain client outcome, never successful client throughput.
The stress abort can interrupt VUs after commit, so that run is not qualified.

Concurrent backfill requests generate real worker traffic, but dual writes may
already have populated the historical target. These requests do not establish
large-volume historical backfill capacity. Dedicated migration tests separately
exercise resume, divergence and source-write races.

A runner-alias error in the first lower mixed run executed create-only work.
The validator now requires every planned lifecycle operation in a mixed artifact
and marks that retained run unqualified. The corrected repeat is separate.
Failed runs remain published; they are not replaced by passing repeats.

The README's table is rendered from independently recomputed `report.json`
files by `python3 scripts/performance/render.py`. CI reruns the validator and
fails if `render.py --check` finds a number or result classification mismatch.

The corrected lower mixed study completed 121 workflows and 1,086 HTTP requests
with no dropped work, semantic failures or accounting/migration discrepancy.
It produced 174 balanced journals and 116 refunds. Its p95 was 21.5 ms and p99
56.4 ms. The paired 25 create arrivals/s baselines acknowledged 1,500 and 1,501
creates over 60 seconds, with p99 112.6 ms and 161.1 ms. These are the observed
passing points, not a maximum-capacity estimate or a confidence interval.

The stress run aborted early, committed 16,909 intents but acknowledged only
16,524 creates, and still had 7,550 events at the five-minute drain deadline.
Its low completed-request latency does not make it qualified. Financial checks
found no duplicate or unbalanced money effects; the delivery recovery budget
failed. The failed higher-rate mixed run and the misconfigured create-only alias
are retained alongside the corrected run, with reasons in each report.

## Docker qualification follow-up

The Docker verification toolchain and revised worker/migration practices are
specified in `docs/production-readiness.md`. The new `target-probe` profile offers
25,000 create arrivals/s for five seconds, with at most 500 generator VUs and
abort-on-drop/error. This is a bounded capacity probe, not the 30-minute target.
A generator-limited failure cannot establish the service's maximum throughput.
A fresh 100-arrivals/s run of the original worker passed, so earlier failures
must be interpreted as observations on shared resources rather than a stable
capacity ceiling. Both original and revised source identities remain recorded.

The subsequent Spring Boot 4.1 studies repeated both 100-arrivals/s runs, the
10-workflow-arrivals/s mixed load and the full stepped stress schedule. They
passed their declared budgets. The stress snapshot drained in 35.5 seconds;
the older undrained run remains retained. Two bounded target probes failed the
offered-work budget and cannot qualify 25K/s. Source overlays whose bytes match
the recorded fingerprints are retained under `evidence/qualification/sources/`.
The independent qualification validator checks their inventory and byte hashes.

The Docker benchmark wrapper writes a fresh `artifacts/benchmark-*` directory
and fails when that study misses its budgets. Use `--allow-unqualified` explicitly
with the validator only to analyze and retain failed capacity observations.
