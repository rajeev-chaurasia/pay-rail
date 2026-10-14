#!/usr/bin/env python3
"""Verify a gated read cohort and rollback on an owned canonical fixture."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("payrail-qual-"):
        parser.error("Owned project required")
    postgres = args.project + "-postgres-1"
    app = args.project + "-app-1"
    for name in (postgres, app):
        info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
            raise ValueError("Foreign service")
    image = json.loads(subprocess.check_output(["docker", "inspect", app]))[0]["Image"]
    credential = "pr_test_cutover_" + uuid.uuid4().hex
    digest = hashlib.sha256(
        ("local-development-pepper-change-me:" + credential).encode()
    ).hexdigest()

    def sql(query):
        return subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                postgres,
                "psql",
                "-X",
                "-At",
                "-U",
                "payrail",
                "-d",
                "payrail",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=query,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    if (
        sql(
            "select cutover_ready from migration_checkpoints where migration_name='payment_intents_v2_backfill';"
        )
        != "t"
    ):
        raise ValueError("Full reconciliation gate must be ready before read cutover")
    sql(
        f"insert into api_keys(tenant_id,key_hash,label) values ('tenant_migration','{digest}','synthetic cutover fixture');"
    )
    canary = args.project + "-read-canary"
    container_args = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        canary,
        "--label",
        "com.docker.compose.project=" + args.project,
        "--network",
        args.project + "_default",
        "-p",
        "127.0.0.1:18081:8080",
        "-e",
        "DATABASE_URL=jdbc:postgresql://postgres:5432/payrail",
        "-e",
        "REDIS_HOST=redis",
        "-e",
        "KAFKA_BOOTSTRAP_SERVERS=kafka:29092",
        "-e",
        "OUTBOX_ENABLED=false",
        "-e",
        "SPRING_KAFKA_LISTENER_AUTO_STARTUP=false",
        "-e",
        "SPRING_KAFKA_ADMIN_AUTO_CREATE=false",
        "-e",
        "MIGRATION_V2_READ_PERCENT=100",
        "-e",
        "MIGRATION_SHADOW_READ_PERCENT=100",
        "-e",
        "JAVA_TOOL_OPTIONS=-Xmx2g",
        image,
    ]
    subprocess.run(container_args, capture_output=True, check=True)

    def read(identifier, version="2026-01-01", canary_read=True):
        base = "http://127.0.0.1:18081" if canary_read else "http://10.240.0.10:18080"
        request = urllib.request.Request(
            base + "/v1/payment_intents/" + identifier,
            headers={
                "Authorization": "Bearer " + credential,
                "PayRail-Version": version,
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    observations = []
    identifier = "hist_000000000001"
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if read(identifier)["amount"] == 101:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        else:
            raise ValueError("Read cohort did not become healthy")
        for ordinal in (1, 25000000, 50000000, 75000000, 100000000):
            item = "hist_" + str(ordinal).zfill(12)
            new = read(item)
            old = read(item, "2025-01-01")
            if (
                new["amount"] != 100 + ordinal % 10000
                or old["state"] != new["status"]
                or new["metadata"]["ordinal"] != ordinal
            ):
                raise ValueError("Read cutover representation mismatch")
            observations.append(
                {
                    "ordinal": ordinal,
                    "amount": new["amount"],
                    "state": new["status"],
                    "versions_agree": True,
                }
            )
        sql(
            "update payment_intents_v2 set amount_minor=999 where source_id='hist_000000000001';"
        )
        fallback = read(identifier)
        if fallback["amount"] != 101:
            raise ValueError("Shadow divergence must fall back to authoritative source")
    finally:
        sql(
            "update payment_intents_v2 set amount_minor=101 where source_id='hist_000000000001';"
        )
        subprocess.run(
            ["docker", "stop", "--timeout", "10", canary],
            capture_output=True,
            check=True,
        )
    rollback = read(identifier, canary_read=False)
    if rollback["amount"] != 101:
        raise ValueError(
            "Original source-read cohort must remain available after rollback"
        )
    args.output.write_text(
        json.dumps(
            {
                "read_cohort": observations,
                "shadow_negative_control": True,
                "source_fallback_amount": fallback["amount"],
                "rollback_source_amount": rollback["amount"],
                "runtime_image": image,
                "limits": "Five boundary reads on a separate 100-percent V2 cohort after full reconciliation; original source readers stay live. A synthetic shadow divergence is repaired. No production ingress or tenant rollout was changed.",
            },
            indent=2,
        )
        + "\n"
    )
    print("Read cutover, shadow divergence fallback and source-read rollback passed")


if __name__ == "__main__":
    main()
