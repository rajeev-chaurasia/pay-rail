#!/usr/bin/env python3
"""Recompute bounded qualification observations without expanding their scope."""

import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_redelivery(report):
    require(
        report["schema"] == "payrail-provider-redelivery-v1",
        "Qualification evidence invalid",
    )
    workers = report["workers"]
    require(
        type(report["configured_redeliveries"]) is int,
        "Redelivery count must be an integer",
    )
    require(
        all(type(value) is int for worker in workers for value in worker.values()),
        "Worker observations must be integers",
    )
    require(
        all(type(value) is int for value in report["snapshot"].values()),
        "Snapshot counters must be integers",
    )
    require(len(workers) == 8, "Qualification evidence invalid")
    require(
        sorted((w["worker"] for w in workers)) == list(range(8)),
        "Qualification evidence invalid",
    )
    require(
        sum((w["completed_calls"] for w in workers))
        == report["configured_redeliveries"],
        "Qualification evidence invalid",
    )
    require(
        1 <= report["configured_redeliveries"] <= 1000000,
        "Qualification evidence invalid",
    )
    require(
        all(
            (
                w["end_nanos"] > w["start_nanos"] and w["completed_calls"] > 0
                for w in workers
            )
        ),
        "Qualification evidence invalid",
    )
    require(
        max((w["start_nanos"] for w in workers))
        < min((w["end_nanos"] for w in workers)),
        "Qualification evidence invalid",
    )
    require(
        report["snapshot"]
        == {
            "journals": 1,
            "entries": 2,
            "delta": 0,
            "inbox_records": 1,
            "provider_operations": 1,
        },
        "Qualification evidence invalid",
    )


def security(root, seal):
    if seal:
        for path in root.glob("*.json"):
            if path.name in {"summary.json", "checksums.json"}:
                continue
            with gzip.open(str(path) + ".gz", "wb") as output:
                output.write(path.read_bytes())
            path.unlink()
    summaries = {}
    for path in sorted(root.glob("*.json.gz")):
        with gzip.open(path, "rt") as handle:
            report = json.load(handle)
        counts = {
            level: 0 for level in ["UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        }
        for result in report.get("Results", []):
            for vulnerability in result.get("Vulnerabilities") or []:
                counts[vulnerability["Severity"]] += 1
        summaries[path.name] = {
            "image": report["ArtifactID"],
            "observed_at": report["CreatedAt"],
            "counts": counts,
        }
    require(summaries, "Qualification evidence invalid")
    final = summaries["runtime-final.json.gz"]["counts"]
    require(
        final["HIGH"] == final["CRITICAL"] == 0,
        "Runtime high/critical security gate failed",
    )
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob("*.json.gz"))
    }
    if seal:
        (root / "checksums.json").write_text(json.dumps(hashes, indent=2) + "\n")
        (root / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    else:
        require(
            hashes == json.loads((root / "checksums.json").read_text()),
            "Security byte inventory changed",
        )
        require(
            summaries == json.loads((root / "summary.json").read_text()),
            "Security summary changed",
        )
    print("Retained runtime security reports recomputed; high/critical gate passed")


def source_archives(root):
    index = json.loads((root / "source-snapshots.json").read_text())
    for run_id, record in index.items():
        require(Path(run_id).name == run_id, "Invalid run identity")
        archive = Path(record["archive"])
        require(
            archive.resolve().is_relative_to((root / "sources").resolve()),
            "Archive must stay in its evidence directory",
        )
        require(
            hashlib.sha256(archive.read_bytes()).hexdigest()
            == record["archive_sha256"],
            "Source archive checksum changed",
        )
        manifest = json.loads(
            (Path("evidence/performance") / run_id / "manifest.json").read_text()
        )
        expected = manifest["environment"]["source_sha256"]
        with tarfile.open(archive) as handle:
            members = handle.getmembers()
            require(
                len(members) == len(expected)
                and {m.name for m in members} == set(expected),
                "Source archive inventory changed",
            )
            for member in members:
                require(
                    member.isfile() and member.size <= 1000000,
                    "Unexpected source archive entry",
                )
                require(
                    hashlib.sha256(handle.extractfile(member).read()).hexdigest()
                    == expected[member.name],
                    "Recorded source bytes changed",
                )
    print("Historical source archives match recorded runtime fingerprints")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal-security", action="store_true")
    args = parser.parse_args()
    root = Path("evidence/qualification")
    compatibility = json.loads((root / "compatibility.json").read_text())
    require(
        compatibility["after_verified"] and compatibility["committed_intents"] == 4,
        "Qualification evidence invalid",
    )
    require(
        compatibility["before_image"] != compatibility["after_image"],
        "Qualification evidence invalid",
    )
    require(len(compatibility["cases"]) == 4, "Qualification evidence invalid")
    require(
        {case["version"] for case in compatibility["cases"]}
        == {"2025-01-01", "2026-01-01"},
        "Qualification evidence invalid",
    )
    redelivery = root / "provider-redelivery.json"
    validate_redelivery(json.loads(redelivery.read_text()))
    print("Provider delivery counts and one-effect snapshot passed")
    source_archives(root)
    security(Path("evidence/security"), args.seal_security)


if __name__ == "__main__":
    main()
