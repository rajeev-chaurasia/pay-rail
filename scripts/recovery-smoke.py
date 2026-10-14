#!/usr/bin/env python3
"""Crash and logical-restore checks on a disposable, synthetic Compose project."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def require(condition, message):
    if not condition:
        raise ValueError(message)


def docker(*args, data=None, check=True):
    return subprocess.run(
        ["docker", *args], input=data, capture_output=True, check=check, timeout=90
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/recovery.json"))
    args = parser.parse_args()
    project = os.environ["RECOVERY_PROJECT"]
    require(project.startswith("payrail-recovery-"), "Disposable project required")
    containers = {
        name: os.environ["RECOVERY_" + name.upper()]
        for name in ("app", "postgres", "kafka")
    }
    images = {}
    for name, container in containers.items():
        info = json.loads(docker("inspect", container).stdout)[0]
        require(
            info["Config"]["Labels"].get("com.docker.compose.project") == project,
            "Container must belong to the disposable project",
        )
        images[name] = info["Image"]
    url = "http://app:8080"
    observations = []

    def call(method, path, body=None, key=None):
        headers = {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
            "PayRail-Version": "2026-01-01",
        }
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(
            url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            observations.append(
                {"method": method, "path": path, "status": response.status}
            )
            return response.status, raw, json.loads(raw)

    def wait_for(probe, description):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                if probe():
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        raise ValueError("Timed out: " + description)

    def sql(statement, database="payrail"):
        return docker(
            "exec",
            containers["postgres"],
            "psql",
            "-U",
            "payrail",
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            statement,
        ).stdout

    def snapshot():
        tables = (
            sql(
                "select tablename from pg_tables where schemaname='public' order by tablename"
            )
            .decode()
            .splitlines()
        )
        # Include every table and every column, with deterministic row ordering.
        return {
            table: hashlib.sha256(
                sql(
                    "select coalesce(jsonb_agg(row_data order by row_data::text), "
                    "'[]'::jsonb) from (select to_jsonb(t) row_data from public."
                    + '"'
                    + table.replace('"', '""')
                    + '" t) rows'
                )
            ).hexdigest()
            for table in tables
        }

    wait_for(lambda: call("GET", "/actuator/health")[2]["status"] == "UP", "startup")
    body = {"amount": 432, "currency": "usd", "captureMethod": "automatic"}
    created = call("POST", "/v1/payment_intents", body, "recovery-create")
    require(created[0] == 201, "Create must commit")
    path = "/v1/payment_intents/" + created[2]["id"]
    docker("stop", "--time", "5", containers["kafka"])
    confirmation = call("POST", path + "/confirm", key="recovery-confirm")
    require(
        confirmation[0] == 202 and confirmation[2]["status"] == "processing",
        "Confirmation must commit before the crash",
    )
    pending = call("GET", path + "/inspect")[2]
    require(
        not pending["journals"]
        and any(e.get("publishedAt") is None for e in pending["events"]),
        "Committed command must still be pending",
    )
    started = time.monotonic()
    docker("kill", "--signal", "KILL", containers["app"])
    docker("kill", "--signal", "KILL", containers["postgres"])
    docker("start", containers["postgres"], containers["kafka"])
    wait_for(
        lambda: docker(
            "exec", containers["postgres"], "pg_isready", "-U", "payrail", check=False
        ).returncode
        == 0,
        "database crash recovery",
    )
    docker("start", containers["app"])

    def settled():
        view = call("GET", path + "/inspect")[2]
        return len(view["journals"]) == 1 and all(
            e.get("publishedAt") for e in view["events"]
        )

    wait_for(settled, "crash recovery and outbox drain")
    recovery_seconds = time.monotonic() - started
    final = call("GET", path + "/inspect")[2]
    require(
        len(final["providerOperations"]) == 1 and final["journals"][0]["balanced"],
        "Recovery must have exactly one provider operation and balanced journal",
    )
    require(
        call("POST", path + "/confirm", key="recovery-confirm")[:2] == confirmation[:2],
        "Confirmation replay must retain exact status and bytes",
    )
    require(call("GET", path)[2]["status"] == "succeeded", "Payment must settle")

    # Freeze the only writer so the full-table comparison is a stable restore oracle.
    docker("stop", "--time", "30", containers["app"])
    before = snapshot()
    dump = docker(
        "exec",
        containers["postgres"],
        "pg_dump",
        "-U",
        "payrail",
        "-d",
        "payrail",
        "-Fc",
    ).stdout
    sql("create database restore_negative", "postgres")
    bad = docker(
        "exec",
        "-i",
        containers["postgres"],
        "pg_restore",
        "-U",
        "payrail",
        "-d",
        "restore_negative",
        "--exit-on-error",
        data=dump[: len(dump) // 2],
        check=False,
    )
    require(bad.returncode != 0, "Truncated backup negative control must fail")
    restore_started = time.monotonic()
    sql("drop database payrail", "postgres")
    sql("create database payrail", "postgres")
    docker(
        "exec",
        "-i",
        containers["postgres"],
        "pg_restore",
        "-U",
        "payrail",
        "-d",
        "payrail",
        "--exit-on-error",
        data=dump,
    )
    require(snapshot() == before, "Every restored table must match the frozen source")
    docker("start", containers["app"])
    wait_for(
        lambda: call("GET", "/actuator/health")[2]["status"] == "UP", "restored startup"
    )
    require(
        call("POST", "/v1/payment_intents", body, "recovery-create")[:2] == created[:2],
        "Restored create replay must retain exact status and bytes",
    )
    require(
        call("POST", path + "/confirm", key="recovery-confirm")[:2] == confirmation[:2],
        "Restored confirmation replay must retain exact status and bytes",
    )
    final = call("GET", path + "/inspect")[2]
    require(
        len(final["journals"]) == len(final["providerOperations"]) == 1
        and final["journals"][0]["balanced"],
        "Restore must preserve one monetary effect",
    )
    result = {
        "project": project,
        "images": images,
        "faults": ["app_sigkill", "postgres_sigkill"],
        "crash_recovery_seconds": recovery_seconds,
        "logical_restore_seconds": time.monotonic() - restore_started,
        "backup_bytes": len(dump),
        "backup_sha256": hashlib.sha256(dump).hexdigest(),
        "table_sha256": before,
        "truncated_backup_rejected": True,
        "journal_count": 1,
        "provider_operation_count": 1,
        "exact_replays": 3,
        "requests": observations,
        "limits": "One synthetic payment; combined crash schedule; stopped-writer logical backup. No PITR, HA, or scale qualification.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Isolated crash recovery and logical backup restoration passed")


if __name__ == "__main__":
    main()
