#!/usr/bin/env python3
"""Read local Docker capacity before any large synthetic migration seed."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def run(args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--objects", type=int, default=100000000)
    parser.add_argument(
        "--output", type=Path, default=Path("evidence/qualification/preflight.json")
    )
    args = parser.parse_args()
    if args.objects < 1:
        parser.error("objects must be positive")
    query = """select json_build_object(
      'source_rows',(select count(*) from payment_intents),
      'target_rows',(select count(*) from payment_intents_v2),
      'source_bytes',pg_total_relation_size('payment_intents'),
      'target_bytes',pg_total_relation_size('payment_intents_v2'))"""
    sizes = json.loads(
        run(
            [
                "docker",
                "exec",
                "payrail-postgres-1",
                "psql",
                "-X",
                "-A",
                "-t",
                "-U",
                "payrail",
                "-d",
                "payrail",
                "-c",
                query,
            ]
        )
    )
    if not sizes["source_rows"] or not sizes["target_rows"]:
        raise SystemExit("A populated sizing pilot is required")
    free_kib = int(
        run(
            [
                "docker",
                "exec",
                "payrail-postgres-1",
                "df",
                "-Pk",
                "/var/lib/postgresql/data",
            ]
        )
        .splitlines()[-1]
        .split()[3]
    )
    info = json.loads(run(["docker", "info", "--format", "{{json .}}"]))
    per_object = (
        sizes["source_bytes"] / sizes["source_rows"]
        + sizes["target_bytes"] / sizes["target_rows"]
    )
    core = int(per_object * args.objects)
    # Explicit planning allowance for WAL, temporary space and other payment relations.
    planned = core * 3
    passed = free_kib * 1024 >= planned
    report = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "target_objects": args.objects,
        "pilot": sizes,
        "docker_cpus": info["NCPU"],
        "docker_memory_bytes": info["MemTotal"],
        "available_volume_bytes": free_kib * 1024,
        "estimated_core_bytes": core,
        "planning_headroom_multiplier": 3,
        "planned_bytes_with_headroom": planned,
        "storage_gate_passed": passed,
        "seed_started": False,
        "limits": "Small-pilot storage extrapolation is a planning estimate, not measured large-scale migration. Re-size on dedicated hardware including indexes, WAL, replicas and backups. No throughput inference.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit("Storage gate failed; large seed was not started")


if __name__ == "__main__":
    main()
