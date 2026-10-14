#!/usr/bin/env python3
"""Bounded synthetic history seed and real service backfill on an owned test host."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--objects", type=int, default=1000000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--reserve-gib", type=int, default=60)
    args = parser.parse_args()
    if (
        not args.project.startswith("payrail-qual-")
        or not 1 <= args.objects <= 100000000
    ):
        parser.error("Only bounded, owned qualification fixtures are supported")
    if not 10 <= args.reserve_gib <= 100:
        parser.error("Disk reserve must be 10..100 GiB")
    postgres = args.project + "-postgres-1"
    info = json.loads(subprocess.check_output(["docker", "inspect", postgres]))[0]
    if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
        raise ValueError("PostgreSQL does not belong to the qualification project")

    def sql(statement):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                postgres,
                "psql",
                "-X",
                "-U",
                "payrail",
                "-d",
                "payrail",
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=True,
            timeout=1800,
        )
        return result.stdout.strip()

    def call(path, method="GET"):
        request = urllib.request.Request(
            "http://10.240.0.10:18080/v1/admin/migrations/payment-v2" + path,
            headers={"X-Admin-Token": "local-admin-token"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            return json.loads(response.read())

    sql(
        "insert into tenants(id,name) values ('tenant_migration','Synthetic migration fixture') on conflict do nothing;"
    )
    existing = int(
        sql("select count(*) from payment_intents where tenant_id='tenant_migration';")
    )
    report = {
        "objects_requested": args.objects,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "seed_chunks": [],
        "backfill_chunks": [],
        "source_initial": existing,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def persist():
        args.output.write_text(json.dumps(report, indent=2) + "\n")

    began = time.monotonic()
    for low in range(existing + 1, args.objects + 1, 100000):
        high = min(low + 99999, args.objects)
        started = time.monotonic()
        sql(
            f"insert into payment_intents(id,tenant_id,amount,currency,capture_method,status,metadata) select 'hist_'||lpad(n::text,12,'0'),'tenant_migration',100+(n%10000),'usd','manual','requires_confirmation',jsonb_build_object('seed',42,'ordinal',n) from generate_series({low},{high}) n;"
        )
        report["seed_chunks"].append(
            {"first": low, "last": high, "seconds": time.monotonic() - started}
        )
        persist()
        free = (
            int(
                subprocess.check_output(
                    [
                        "docker",
                        "exec",
                        postgres,
                        "sh",
                        "-c",
                        "df -Pk /var/lib/postgresql/data | tail -1 | awk '{print $4}'",
                    ]
                )
            )
            * 1024
        )
        if free < args.reserve_gib * 1024**3:
            raise ValueError(
                "Qualification disk reserve exhausted; stopped bounded seed"
            )
    report["seed_seconds"] = time.monotonic() - began
    report["source_rows"] = int(
        sql("select count(*) from payment_intents where tenant_id='tenant_migration';")
    )
    report["source_bytes"] = int(
        sql("select pg_total_relation_size('payment_intents');")
    )
    persist()
    if args.seed_only:
        return
    # Expanding a direct historical fixture inserts keys behind the old high-water mark.
    # Reset only this isolated test checkpoint; keep existing compatible target rows.
    sql(
        "update migration_checkpoints set last_key='',rows_processed=0,cutover_ready=false where migration_name='payment_intents_v2_backfill';"
    )
    began = time.monotonic()
    while True:
        started = time.monotonic()
        result = call("/backfill?batchSize=5000", "POST")
        report["backfill_chunks"].append(
            {"processed": result["processed"], "seconds": time.monotonic() - started}
        )
        if len(report["backfill_chunks"]) % 100 == 0 or result["processed"] == 0:
            persist()
        if result["processed"] == 0:
            break
    report["backfill_seconds"] = time.monotonic() - began
    report["reconciliation"] = call("/reconcile")
    report["gate"] = call("/gate-cutover", "POST")
    report["target_rows"] = int(
        sql(
            "select count(*) from payment_intents_v2 where tenant_id='tenant_migration';"
        )
    )
    report["target_bytes"] = int(
        sql("select pg_total_relation_size('payment_intents_v2');")
    )
    if (
        any(
            report["reconciliation"][name]
            for name in ("missing", "extra", "mismatched")
        )
        or not report["gate"]["cutover_ready"]
        or report["source_rows"] != report["target_rows"]
    ):
        persist()
        raise ValueError("Migration qualification reconciliation failed")
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    persist()
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("seed_chunks", "backfill_chunks")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
