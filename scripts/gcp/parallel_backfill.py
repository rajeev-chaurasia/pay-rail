#!/usr/bin/env python3
"""Checkpointed bounded range workers for an owned synthetic history fixture."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--first", type=int, required=True)
    parser.add_argument("--last", type=int, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff", action="store_true")
    args = parser.parse_args()
    if (
        not args.project.startswith("payrail-qual-")
        or not 1 <= args.first <= args.last <= 100000000
        or not 1 <= args.workers <= 8
    ):
        parser.error("Bounded owned history range required")
    container = args.project + "-postgres-1"
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
        raise ValueError("Foreign database")

    def sql(statement):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-X",
                "-qAt",
                "-U",
                "payrail",
                "-d",
                "payrail",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=True,
            timeout=300,
        )
        return result.stdout.strip()

    def key(ordinal):
        return "hist_" + str(ordinal).zfill(12)

    spans = []
    size = (args.last - args.first + args.workers) // args.workers
    for index in range(args.workers):
        low = args.first + index * size
        high = min(args.last, low + size - 1)
        if low > high:
            continue
        name = "qualification_range_" + str(low) + "_" + str(high)
        sql(
            f"insert into migration_checkpoints(migration_name,last_key) values ('{name}','{key(low - 1)}') on conflict do nothing;"
        )
        spans.append((name, low, high))
    began = time.monotonic()
    outcomes = []

    def worker(span):
        name, low, high = span
        chunks = []
        while True:
            started = time.monotonic()
            count = int(
                sql(f"""begin;
              select 1 from migration_checkpoints where migration_name='{name}' for update;
              with chunk as materialized (
                select p.* from payment_intents p where p.id>(select last_key from migration_checkpoints where migration_name='{name}')
                and p.id<='{key(high)}' and p.tenant_id='tenant_migration' order by p.id limit 5000 for key share
              ), copied as (
                insert into payment_intents_v2(source_id,tenant_id,amount_minor,currency_code,capture_method,lifecycle_status,
                  capturable_minor,captured_minor,refunded_minor,source_version,metadata,source_created_at,source_updated_at)
                select id,tenant_id,amount,currency,capture_method,status,amount_capturable,amount_received,amount_refunded,
                  version,metadata,created_at,updated_at from chunk
                on conflict(source_id) do update set amount_minor=excluded.amount_minor,currency_code=excluded.currency_code,
                  capture_method=excluded.capture_method,lifecycle_status=excluded.lifecycle_status,capturable_minor=excluded.capturable_minor,
                  captured_minor=excluded.captured_minor,refunded_minor=excluded.refunded_minor,source_version=excluded.source_version,
                  metadata=excluded.metadata,source_updated_at=excluded.source_updated_at,migrated_at=now()
                where payment_intents_v2.source_version<=excluded.source_version returning source_id
              ), progress as (
                update migration_checkpoints set last_key=coalesce((select max(id) from chunk),last_key),
                  rows_processed=rows_processed+(select count(*) from chunk),updated_at=now()
                where migration_name='{name}' returning rows_processed
              ) select count(*) from chunk;
              commit;""").splitlines()[-1]
            )
            chunks.append({"rows": count, "seconds": time.monotonic() - started})
            if len(chunks) % 100 == 0 or count == 0:
                Path(str(args.output) + "." + str(low) + ".json").write_text(
                    json.dumps({"first": low, "last": high, "chunks": chunks}, indent=2)
                    + "\n"
                )
            if count == 0:
                return {
                    "first": low,
                    "last": high,
                    "rows": sum(c["rows"] for c in chunks),
                    "chunk_count": len(chunks),
                }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outcomes = list(pool.map(worker, spans))
    target = int(
        sql(
            "select count(*) from payment_intents_v2 where tenant_id='tenant_migration';"
        )
    )
    if args.handoff:
        if target != args.last:
            raise ValueError("Cannot advance coordinator over incomplete history")
        sql(
            f"update migration_checkpoints set last_key='{key(args.last)}',rows_processed={args.last},cutover_ready=false,updated_at=now() where migration_name='payment_intents_v2_backfill';"
        )
    args.output.write_text(
        json.dumps(
            {
                "workers": args.workers,
                "ranges": outcomes,
                "target_history_rows": target,
                "seconds": time.monotonic() - began,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "handoff": args.handoff,
                "limits": "Bounded synthetic history ranges; all constraints/version guards remain enabled. Full canonical reconciliation must follow before cutover.",
            },
            indent=2,
        )
        + "\n"
    )
    print("Parallel history backfill complete; target rows=" + str(target))


if __name__ == "__main__":
    main()
