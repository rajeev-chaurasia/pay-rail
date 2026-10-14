#!/usr/bin/env python3
"""Observe bounded post-overload recovery on an owned synthetic project."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("payrail-qual-"):
        raise ValueError("Owned bounded qualification project required")
    container = args.project + "-postgres-1"
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
        raise ValueError("Foreign PostgreSQL container")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "maximum_observation_seconds": 600,
        "samples": [],
        "limits": "Post-overload recovery observation, not a sustained throughput qualification gate.",
    }
    epoch = time.monotonic()
    while True:
        raw = subprocess.check_output(
            ["docker", "exec", container, "psql", "-X", "-At", "-U", "payrail",
             "-d", "payrail", "-c",
             "select jsonb_build_object('observed_at',now(),'pending',count(*),'oldest',min(created_at)) from outbox_events where published_at is null;"],
            text=True,
            timeout=30,
        )
        sample = json.loads(raw)
        report["samples"].append(sample)
        report["elapsed_seconds"] = time.monotonic() - epoch
        report["drained"] = sample["pending"] == 0
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        if report["drained"] or report["elapsed_seconds"] >= 600:
            break
        time.sleep(10)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
