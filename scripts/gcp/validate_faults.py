#!/usr/bin/env python3
"""Recompute observed fault classes, exact replay digests and original effects."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

RECORD = struct.Struct("<QIBBHHIQH32s32s")


def analyze(path):
    summary = json.loads(Path(str(path) + ".summary.json").read_text())
    fixtures = json.loads(Path(str(path) + ".fixtures.json").read_text())["fixtures"]
    seen = bytearray(summary["attempted_actions"])
    counts = Counter()
    failures = 0
    digest = hashlib.sha256()
    first_started, last_finished = None, 0
    with path.open("rb") as handle:
        while chunk := handle.read(RECORD.size):
            if len(chunk) != RECORD.size:
                raise ValueError("Truncated fault record")
            digest.update(chunk)
            (
                ordinal,
                index,
                kind,
                passed,
                status,
                retry,
                duration,
                started,
                verification,
                response_hash,
                verification_hash,
            ) = RECORD.unpack(chunk)
            if (
                ordinal >= len(seen)
                or seen[ordinal]
                or index >= len(fixtures)
                or kind not in (1, 2, 3)
            ):
                raise ValueError("Invalid or repeated fault action")
            seen[ordinal] = 1
            counts[str(kind)] += 1
            expected = bytes.fromhex(fixtures[index]["capture_sha256"])
            valid = passed == 1
            if ordinal < len(fixtures):
                valid = (
                    valid
                    and kind == 3
                    and index == ordinal
                    and status == retry == verification == 200
                    and response_hash == verification_hash == expected
                )
            elif kind == 2:
                valid = valid and status == 409 and retry == verification == 0
            elif kind == 3:
                valid = (
                    valid
                    and status == retry == 200
                    and verification == 0
                    and response_hash == expected
                )
            else:
                valid = (
                    valid
                    and status == 200
                    and retry == verification == 0
                    and response_hash == expected
                )
            failures += int(not valid)
            first_started = min(first_started or started, started)
            last_finished = max(last_finished, started + duration * 1000)
    if (
        not all(seen)
        or counts != Counter(summary["class_counts"])
        or failures != summary["failures"]
    ):
        raise ValueError("Raw fault observations differ from summary")
    if (
        len(seen) - failures != summary["counted_actions"]
        or len(fixtures) != summary["original_capture_response_losses"]
    ):
        raise ValueError("Observed action or original-effect count differs")
    return {
        "attempted_actions": len(seen),
        "observed_successful_fault_actions": len(seen) - failures,
        "original_capture_response_losses": len(fixtures),
        "class_counts": dict(counts),
        "failures": failures,
        "elapsed_observed_seconds": (last_finished - first_started) / 1e9,
        "raw_sha256": digest.hexdigest(),
        "protocol_gate_passed": failures == 0,
        "limits": "Counted HTTP duplicate captures, fingerprint conflicts and discarded committed bodies. Financial reconciliation and infrastructure drills are separate required observations. Not one million process crashes or provider timeouts.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    args = parser.parse_args()
    result = analyze(args.raw)
    args.raw.with_suffix(".report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
