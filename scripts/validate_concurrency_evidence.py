#!/usr/bin/env python3
import csv
import hashlib
import json
import math
import argparse
import copy
import sys
from pathlib import Path


SCHEMA = "payrail-concurrency-evidence-v1"
POLICY = "postgres-idempotency-row-lock-v1"
SOURCE_PATHS = ["pom.xml", "src/main/java", "src/main/resources/db/migration"]


def fail(message: str) -> None:
    raise SystemExit(f"concurrency evidence invalid: {message}")


def source_fingerprint(paths: list[str]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for item in paths:
        path = Path(item)
        files.extend(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else files.append(path)
    for path in sorted(files, key=lambda p: str(p)):
        if not path.is_file():
            fail(f"missing source path {path}")
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"phase", "worker", "start_nanos", "end_nanos", "outcome", "action_executed"}
    if not rows or set(rows[0]) != required:
        fail("raw.csv is empty or has the wrong columns")
    return rows


def validate_intervals(rows: list[dict[str, str]], phase: str, concurrency: int) -> list[dict[str, str]]:
    selected = [row for row in rows if row["phase"] == phase]
    if len(selected) != concurrency:
        fail(f"{phase} has {len(selected)} samples, expected {concurrency}")
    if sorted(int(row["worker"]) for row in selected) != list(range(concurrency)):
        fail(f"{phase} has duplicate or missing worker IDs")
    if any(not row["outcome"].strip() or row["action_executed"] not in {"true", "false"} for row in selected):
        fail(f"{phase} has invalid outcomes or action flags")
    starts = [int(row["start_nanos"]) for row in selected]
    ends = [int(row["end_nanos"]) for row in selected]
    if not all(math.isfinite(value) for value in starts + ends):
        fail(f"{phase} contains a nonfinite timestamp")
    if any(end <= start for start, end in zip(starts, ends)):
        fail(f"{phase} contains an invalid interval")
    if max(starts) >= min(ends):
        fail(f"{phase} requests did not overlap")
    return selected


def validate(manifest, rows):
    if manifest.get("schema_version") != SCHEMA or manifest.get("policy") != POLICY:
        fail("unsupported schema or policy")
    if manifest.get("source_paths") != SOURCE_PATHS:
        fail("source path inventory is incomplete or altered")
    if source_fingerprint(manifest.get("source_paths", [])) != manifest.get("source_tree_sha256"):
        fail("source fingerprint does not match the current tree")
    concurrency = int(manifest["concurrency"])
    if concurrency < 2 or len(rows) != concurrency * 2:
        fail("missing concurrency or unexpected sample count")
    if any(row["phase"] not in {"guarded", "unguarded_control"} for row in rows):
        fail("unknown scenario")
    guarded = validate_intervals(rows, "guarded", concurrency)
    control = validate_intervals(rows, "unguarded_control", concurrency)
    guarded_attempts = sum(row["action_executed"] == "true" for row in guarded)
    guarded_effects = len({row["outcome"] for row in guarded})
    control_effects = len({row["outcome"] for row in control})
    if guarded_attempts != manifest.get("guarded_action_attempts") or guarded_attempts != 1:
        fail("guarded action-attempt count does not recompute to one")
    if guarded_effects != manifest.get("guarded_committed_effects") or guarded_effects != 1:
        fail("guarded effect count does not recompute to one")
    if control_effects != manifest.get("negative_control_committed_effects"):
        fail("negative-control effect count does not match raw samples")
    if control_effects <= 1 or manifest.get("negative_control_detected") is not True:
        fail("negative control was absent or not detected")
    if any(row["action_executed"] != "true" for row in control):
        fail("control action was not executed by every worker")
    return control_effects


def self_test(manifest, rows):
    mutations = []
    duplicate = copy.deepcopy(rows)
    duplicate[1]["worker"] = duplicate[0]["worker"]
    mutations.append((manifest, duplicate))
    unknown = copy.deepcopy(rows)
    unknown[0]["phase"] = "unknown"
    mutations.append((manifest, unknown))
    blank = copy.deepcopy(rows)
    blank[0]["outcome"] = ""
    mutations.append((manifest, blank))
    serial = copy.deepcopy(rows)
    for index, row in enumerate(serial):
        row["start_nanos"] = str(index * 2)
        row["end_nanos"] = str(index * 2 + 1)
    mutations.append((manifest, serial))
    wrong = copy.deepcopy(manifest)
    wrong["guarded_committed_effects"] = 2
    mutations.append((wrong, rows))
    wrong_paths = copy.deepcopy(manifest)
    wrong_paths["source_paths"] = []
    mutations.append((wrong_paths, rows))
    absent = copy.deepcopy(rows)
    for row in absent:
        if row["phase"] == "unguarded_control":
            row["outcome"] = "one-effect"
    mutations.append((manifest, absent))
    for changed_manifest, changed_rows in mutations:
        try:
            validate(changed_manifest, changed_rows)
        except SystemExit:
            continue
        fail("validator accepted a tampered negative control")
    print(f"Validator rejected {len(mutations)} tampered cases")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="evidence/concurrency")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    directory = Path(args.directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = load_rows(directory / "raw.csv")
    hashes = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    required = {"raw.csv", "manifest.json", "producer.sha256"}
    if set(hashes) != required:
        fail("checksum inventory differs from required files")
    for name, expected in hashes.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            fail(f"checksum mismatch for {name}")
    producer = [Path("src/test/java/com/payrail/ConcurrencyEvidenceHarness.java"), Path(__file__)]
    digest = hashlib.sha256()
    for path in producer:
        digest.update(path.read_bytes())
    if (directory / "producer.sha256").read_text().strip() != digest.hexdigest():
        fail("producer or validator changed; reproduce evidence")
    effects = validate(manifest, rows)
    if args.self_test:
        self_test(manifest, rows)
    print(f"validated {len(rows)} overlapping samples: guarded=1, negative_control={effects}")


if __name__ == "__main__":
    main()
