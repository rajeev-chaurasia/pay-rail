#!/usr/bin/env python3
"""Recompute offered/accepted/dropped traffic from compact raw records."""

import argparse
from array import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct

RECORD = struct.Struct("<QQIHH")


def analyze(path):
    summary = json.loads(Path(str(path) + ".summary.json").read_text())
    seen = bytearray(summary["offered"])
    durations = array("I")
    counts = Counter()
    statuses = Counter()
    accepted_seconds = Counter()
    raw_hash = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(RECORD.size):
            raw_hash.update(chunk)
            if len(chunk) != RECORD.size:
                raise ValueError("Truncated raw record")
            ordinal, started, duration, status, flags = RECORD.unpack(chunk)
            if ordinal >= len(seen) or seen[ordinal] or flags not in (0, 1, 2):
                raise ValueError("Invalid or duplicate raw arrival")
            seen[ordinal] = 1
            if flags == 2:
                counts["dropped"] += 1
                if status or duration:
                    raise ValueError("Dropped work must not report a completed request")
                continue
            scheduled = ordinal * 1000000 // summary["offered_rate"]
            durations.append(duration + max(0, started - scheduled))
            statuses[str(status)] += 1
            if flags == 1:
                if status != 201:
                    raise ValueError("Accepted request has wrong HTTP status")
                counts["accepted"] += 1
                accepted_seconds[started // 1000000] += 1
            else:
                counts["unexpected"] += 1
    if not all(seen) or any(
        counts[k] != summary[k] for k in ("accepted", "dropped", "unexpected")
    ):
        raise ValueError("Raw observations do not match summary")
    ordered = sorted(durations)

    def percentile(fraction):
        if not ordered:
            return 0
        position = (len(ordered) - 1) * fraction
        low, high = math.floor(position), math.ceil(position)
        return (ordered[low] + (ordered[high] - ordered[low]) * (position - low)) / 1000

    qualified = (
        counts["dropped"] == counts["unexpected"] == 0
        and counts["accepted"] == summary["offered"]
        and percentile(0.95) < 1000
        and percentile(0.99) < 2000
    )
    return {
        **summary,
        "statuses": dict(statuses),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "accepted_by_start_second": dict(sorted(accepted_seconds.items())),
        "client_budget_passed": qualified,
        "sustained_target_interval": summary["offered_rate"] == 25000
        and summary["duration_seconds"] >= 1800,
        "sha256": raw_hash.hexdigest(),
        "limits": "Create-only new mutations. Client gate only; database counts, reconciliation and outbox drain are additional required gates.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    args = parser.parse_args()
    report = analyze(args.raw)
    args.raw.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
