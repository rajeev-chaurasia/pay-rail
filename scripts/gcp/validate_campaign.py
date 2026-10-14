#!/usr/bin/env python3
"""Recompute retained cloud observations without turning failed targets into passes."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from validate_load import analyze as analyze_load
from validate_faults import analyze as analyze_faults

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "performance"))
from validate import financial_invariants


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def migration_invariants(migration, parallel, foreground):
    require(migration["source_rows"] == migration["target_rows"] == 100000000,
            "Historical object count differs")
    for reconciliation in (migration["reconciliation"], migration["gate"]):
        require(all(reconciliation[k] == 0 for k in ("missing", "extra", "mismatched"))
                and reconciliation["source_total"] == reconciliation["target_total"],
                "Canonical representations differ")
    require(migration["gate"]["cutover_ready"], "Read gate was not ready")
    position = 18500001
    for item in parallel["ranges"]:
        require(item["first"] == position and item["rows"] == item["last"] - position + 1,
                "Parallel ranges overlap or omit rows")
        position = item["last"] + 1
    require(position == 100000001 and parallel["handoff"], "Range handoff incomplete")
    counts = Counter()
    ordinal = 0
    for line in foreground.splitlines():
        item = json.loads(line)
        require(item["ordinal"] == ordinal, "Foreground ordinals are not contiguous")
        if "missed" in item:
            counts["missed_arrivals"] += item["missed"]
            ordinal += item["missed"]
        else:
            counts["attempted"] += 1
            counts["accepted" if item["status"] == 201 else "errors"] += 1
            ordinal += 1
    require(all(counts[k] == migration["foreground"][k] for k in
                ("attempted", "accepted", "errors", "missed_arrivals")),
            "Foreground summary differs from raw observations")


def recovery_invariants(crash):
    require(len(crash["rounds"]) == 5 and len(crash["actions"]) == 20
            and crash["observed_fault_actions"] == 20, "Recovery schedule incomplete")
    effects = set()
    for action in crash["actions"]:
        require(action["before_running"] and not action["after_running"],
                "Fault boundary was not observed")
    for item in crash["rounds"]:
        view = item["inspection"]
        require(item["status"] == "succeeded" and item["captured_minor"] == 432
                and item["exact_confirm_replay"] and len(view["journals"]) == 1
                and len(view["providerOperations"]) == 1, "Recovered effect differs")
        journal = view["journals"][0]
        entries = journal["entries"]
        require(sum(e["debit"] for e in entries) == sum(e["credit"] for e in entries) == 432
                and len(entries) == 2 and journal["effectKey"] not in effects,
                "Recovered journal is duplicated or unbalanced")
        effects.add(journal["effectKey"])
        require(all(e["publishedAt"] for e in view["events"]), "Recovery outbox not drained")


def validate(directory, raw_directory=None):
    manifest = read(directory / "checksums.json")
    actual_files = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file() and p.name != "checksums.json"}
    require(actual_files == set(manifest), "Unsealed or missing evidence files")
    for name, digest in manifest.items():
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest,
                "Evidence checksum differs: " + name)
    m = read(directory / "migration/migration-100m.json")
    migration_invariants(m, read(directory / "migration/parallel-backfill.json"),
                         gzip.decompress((directory / "migration/migration-100m.json.foreground.jsonl.gz").read_bytes()).decode())
    recovery_invariants(read(directory / "crash-drill.json"))
    for suffix in ("first", "paced"):
        require(not financial_invariants(read(directory / ("fault-snapshot-after-" + suffix + ".json.gz"))),
                "Independent fault financial reconciliation failed")
    paced = read(directory / "http/fault-million-paced.report.json")
    require(paced["observed_successful_fault_actions"] == 1000000
            and paced["failures"] == 0 and paced["original_capture_response_losses"] == 4096
            and sum(paced["class_counts"].values()) == 1000000, "Paced campaign protocol differs")
    cutover = read(directory / "migration/cutover-drill.json")
    require(len(cutover["read_cohort"]) == 5 and all(i["versions_agree"] for i in cutover["read_cohort"])
            and cutover["shadow_negative_control"] and cutover["source_fallback_amount"] == cutover["rollback_source_amount"] == 101,
            "Read cutover or divergence rollback differs")
    database = read(directory / "post-campaign-database.json")["results"]
    paced_snapshot = read(directory / "fault-snapshot-after-paced.json.gz")
    settlement = database["fault_settlements"]
    require(settlement["payments"] == settlement["succeeded"] == len(paced_snapshot["payments"])
            and settlement["journals"] == len(paced_snapshot["journals"])
            and settlement["entries"] == len(paced_snapshot["entries"])
            and settlement["unbalanced"] == 0, "Post-restart accounting counts differ")
    require(all(row["unpublished"] == 0 for row in database["outbox"]), "Final outbox not drained")
    rows = {row["run"]: row for row in database["load_mutations"]}
    loads = {}
    with tempfile.TemporaryDirectory() as temporary:
        for compressed in (directory / "http").glob("*.bin.gz"):
            if compressed.name.startswith("fault"):
                continue
            path = Path(temporary) / compressed.name.removesuffix(".gz")
            path.write_bytes(gzip.decompress(compressed.read_bytes()))
            sidecar = directory / "http" / (path.name + ".summary.json")
            Path(str(path) + ".summary.json").write_bytes(sidecar.read_bytes())
            result = analyze_load(path)
            row = rows.get(result["run_id"])
            if row is None:
                require(result["run_id"] in ("cloud-index-5000", "cloud-index-25000")
                        and not result["client_budget_passed"], "Missing database proof for a passing or unknown run")
            else:
                require(result["accepted"] <= row["committed"] <= result["accepted"] + result["unexpected"],
                        "Committed mutation count differs from observed acknowledgements")
                require(row["committed"] == row["completed_201"] == row["unique_payments"] == row["matching_targets"],
                        "Committed load effects or target representations differ")
            loads[result["run_id"]] = {k: result[k] for k in
                                      ("accepted", "dropped", "unexpected", "p95_ms", "p99_ms", "client_budget_passed")}
            loads[result["run_id"]]["database_run_counts_verified"] = row is not None
        faults = {}
        if raw_directory:
            assets = {item["name"]: item for item in read(directory / "release-assets.json")}
            require({p.name for p in raw_directory.glob("fault-million*.bin.gz")} == set(assets),
                    "Both retained million-action raw assets are required")
            for compressed in raw_directory.glob("fault-million*.bin.gz"):
                require(hashlib.sha256(compressed.read_bytes()).hexdigest() == assets[compressed.name]["sha256"],
                        "Compressed release asset checksum differs")
                path = Path(temporary) / compressed.name.removesuffix(".gz")
                path.write_bytes(gzip.decompress(compressed.read_bytes()))
                for suffix in (".summary.json", ".fixtures.json"):
                    Path(str(path) + suffix).write_bytes((directory / "http" / (path.name + suffix)).read_bytes())
                faults[path.name] = analyze_faults(path)
                require(faults[path.name] == read(directory / "http" / path.with_suffix(".report.json").name),
                        "Fault report differs from recomputed raw records")
    cleanup = read(directory / "cloud-lifecycle.json")
    require(cleanup["state"] == "cleaned" and cleanup["baseline"] == cleanup["baseline_after"],
            "Cloud cleanup or existing service baseline differs")
    return {"historical_objects": m["source_rows"], "foreground_missed_arrivals": m["foreground"]["missed_arrivals"],
            "loads": loads, "recomputed_faults": faults,
            "limits": "Checksums establish file consistency, not independent publisher attestation. Full fault raw records require the release assets. Failed capacity gates stay failed; this does not certify production readiness."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--raw-directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.directory, args.raw_directory), indent=2))
