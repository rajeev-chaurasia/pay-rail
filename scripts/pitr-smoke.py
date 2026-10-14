#!/usr/bin/env python3
"""Physical backup and named-point WAL recovery using only disposable fixtures."""

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


def docker(*args, check=True):
    return subprocess.run(
        ["docker", *args], capture_output=True, check=check, timeout=120
    )


def wait_for(probe, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise ValueError("Timed out: " + description)


def sql(container, statement):
    return (
        docker(
            "exec",
            container,
            "psql",
            "-U",
            "payrail",
            "-d",
            "payrail",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            statement,
        )
        .stdout.decode()
        .strip()
    )


def snapshot(container):
    tables = sql(
        container,
        "select tablename from pg_tables where schemaname='public' order by tablename",
    ).splitlines()
    return {
        table: hashlib.sha256(
            sql(
                container,
                "select coalesce(jsonb_agg(row_data order by row_data::text), "
                "'[]'::jsonb) from (select to_jsonb(t) row_data from public."
                + '"'
                + table.replace('"', '""')
                + '" t) rows',
            ).encode()
        ).hexdigest()
        for table in tables
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/pitr.json"))
    args = parser.parse_args()
    project = os.environ["PITR_PROJECT"]
    require(project.startswith("payrail-pitr-"), "Disposable PITR project required")
    containers = {
        name: os.environ["PITR_" + name.upper()]
        for name in ("postgres", "restored", "negative", "app", "restored_app")
    }
    images = {}
    for name, container in containers.items():
        info = json.loads(docker("inspect", container).stdout)[0]
        require(
            info["Config"]["Labels"].get("com.docker.compose.project") == project,
            "Every container must belong to this disposable project",
        )
        images[name] = info["Image"]
    source = containers["postgres"]
    records = []
    replays = []

    def check_replay(operation, original, replayed):
        require(original[:2] == replayed[:2], operation + " must replay exactly")
        replays.append(
            {
                "operation": operation,
                "original_status": original[0],
                "replayed_status": replayed[0],
                "original_sha256": hashlib.sha256(original[1]).hexdigest(),
                "replayed_sha256": hashlib.sha256(replayed[1]).hexdigest(),
            }
        )

    def call(method, path, body=None, key=None, restored=False):
        headers = {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
            "PayRail-Version": "2026-01-01",
        }
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(
            ("http://restored-app:8080" if restored else "http://app:8080") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            records.append(
                {
                    "restored": restored,
                    "method": method,
                    "path": path,
                    "status": response.status,
                }
            )
            return response.status, raw, json.loads(raw)

    wait_for(
        lambda: call("GET", "/actuator/health")[2]["status"] == "UP", "source startup"
    )
    body = {"amount": 432, "currency": "usd", "captureMethod": "automatic"}
    created = call("POST", "/v1/payment_intents", body, "pitr-create")
    require(created[0] == 201, "Initial create must commit")
    path = "/v1/payment_intents/" + created[2]["id"]
    backup_started = time.monotonic()
    # Throttle this tiny backup to guarantee an observable live-write overlap.
    backup = subprocess.Popen(
        [
            "docker",
            "exec",
            "-u",
            "postgres",
            source,
            "pg_basebackup",
            "-U",
            "payrail",
            "-D",
            "/backups/base",
            "-X",
            "stream",
            "-c",
            "fast",
            "--max-rate=1M",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(
            lambda: sql(source, "select count(*) from pg_stat_progress_basebackup")
            == "1",
            "physical backup progress",
        )
        progress_before = sql(source, "select phase from pg_stat_progress_basebackup")
        live_body = {"amount": 345, "currency": "usd", "captureMethod": "manual"}
        live = call("POST", "/v1/payment_intents", live_body, "pitr-live-create")
        live_path = "/v1/payment_intents/" + live[2]["id"]
        call("POST", live_path + "/confirm", key="pitr-live-confirm")
        captured = call(
            "POST", live_path + "/capture", {"amount": 345}, "pitr-live-capture"
        )
        require(
            captured[2]["status"] == "succeeded",
            "Live capture must commit during backup",
        )
        progress_after = sql(source, "select phase from pg_stat_progress_basebackup")
        require(
            progress_before and progress_after,
            "Live mutations must overlap physical backup",
        )
        _, error = backup.communicate(timeout=120)
        require(
            backup.returncode == 0, "Physical backup must complete: " + error.decode()
        )
    finally:
        if backup.poll() is None:
            backup.kill()
            backup.communicate()
    backup_seconds = time.monotonic() - backup_started
    docker("exec", "-u", "postgres", source, "pg_verifybackup", "/backups/base")
    manifest_hash = (
        docker("exec", source, "sha256sum", "/backups/base/backup_manifest")
        .stdout.decode()
        .split()[0]
    )
    confirmation = call("POST", path + "/confirm", key="pitr-confirm")

    def drained():
        views = [call("GET", item + "/inspect")[2] for item in (path, live_path)]
        return all(
            len(v["journals"]) == 1 and all(e.get("publishedAt") for e in v["events"])
            for v in views
        )

    wait_for(drained, "pre-target settlement and outbox drain")
    target_name = "payrail_before_refund"
    target_lsn = sql(source, "select pg_create_restore_point('payrail_before_refund')")
    expected = snapshot(source)
    refund = call("POST", path + "/refunds", {"amount": 100}, "pitr-refund")
    require(refund[0] == 200, "Post-target refund must commit on source")
    late = call("POST", "/v1/payment_intents", body, "pitr-late-create")
    require(late[0] == 201, "Post-target sentinel must commit")
    source_after_target = snapshot(source)
    segment = sql(source, "select pg_walfile_name(pg_current_wal_lsn())")
    sql(source, "select pg_switch_wal()")
    wait_for(
        lambda: docker(
            "exec", source, "test", "-f", "/archive/" + segment, check=False
        ).returncode
        == 0,
        "target WAL archive acknowledgement",
    )
    archive_hashes = (
        docker("exec", source, "sh", "-c", "sha256sum /archive/*")
        .stdout.decode()
        .splitlines()
    )
    # Prepare independent copies. The negative copy has no archived post-backup WAL.
    for destination in ("/restore/data", "/negative/data"):
        docker(
            "exec",
            "-u",
            "postgres",
            source,
            "sh",
            "-c",
            f"mkdir {destination} && cp -a /backups/base/. {destination}/ && touch {destination}/recovery.signal",
        )
        command = "cp /archive/%f %p" if destination.startswith("/restore") else "false"
        config = (
            "\nrestore_command = '" + command + "'\n"
            "recovery_target_name = '" + target_name + "'\n"
            "recovery_target_action = 'promote'\narchive_mode = 'off'\n"
        )
        docker(
            "exec",
            "-u",
            "postgres",
            source,
            "sh",
            "-c",
            'printf "%s" "$1" >> "$2/postgresql.auto.conf"',
            "sh",
            config,
            destination,
        )
    docker("start", containers["negative"])
    wait_for(
        lambda: json.loads(docker("inspect", containers["negative"]).stdout)[0][
            "State"
        ]["Status"]
        == "exited",
        "missing-WAL negative control",
        timeout=60,
    )
    negative_info = json.loads(docker("inspect", containers["negative"]).stdout)[0]
    negative_log = docker("logs", containers["negative"]).stderr.decode()
    require(
        negative_info["State"]["ExitCode"] != 0
        and "recovery ended before configured recovery target was reached"
        in negative_log,
        "Missing WAL must fail before target instead of accepting a partial restore",
    )
    recovery_started = time.monotonic()
    docker("start", containers["restored"])
    wait_for(
        lambda: docker(
            "exec", containers["restored"], "pg_isready", "-U", "payrail", check=False
        ).returncode
        == 0,
        "recovered database readiness",
    )
    require(
        sql(containers["restored"], "select pg_is_in_recovery()") == "f",
        "Target must promote",
    )
    actual = snapshot(containers["restored"])
    require(actual == expected, "Every public table must match the pre-refund target")
    # Outbox and consumers remain fenced on the restored API until operator reconciliation.
    docker("start", containers["restored_app"])
    wait_for(
        lambda: call("GET", "/actuator/health", restored=True)[2]["status"] == "UP",
        "fenced restored API startup",
    )
    check_replay(
        "create",
        created,
        call("POST", "/v1/payment_intents", body, "pitr-create", restored=True),
    )
    check_replay(
        "confirm",
        confirmation,
        call("POST", path + "/confirm", key="pitr-confirm", restored=True),
    )
    payment = call("GET", path, restored=True)[2]
    require(
        payment["status"] == "succeeded" and payment["amountRefunded"] == 0,
        "Later source refund must be absent at target",
    )
    inspection = call("GET", path + "/inspect", restored=True)[2]
    require(
        len(inspection["journals"]) == len(inspection["providerOperations"]) == 1
        and inspection["journals"][0]["balanced"],
        "Restored settlement must remain unique and balanced",
    )
    restore_seconds = time.monotonic() - recovery_started
    # Synthetic-only write acceptance proves restored sequences/constraints and deduplication.
    fresh_refund = call(
        "POST",
        path + "/refunds",
        {"amount": 100},
        "pitr-restored-refund",
        restored=True,
    )
    check_replay(
        "refund",
        fresh_refund,
        call(
            "POST",
            path + "/refunds",
            {"amount": 100},
            "pitr-restored-refund",
            restored=True,
        ),
    )
    final = call("GET", path + "/inspect", restored=True)[2]
    require(
        len(final["journals"]) == 2 and all(j["balanced"] for j in final["journals"]),
        "Restored writer must append exactly one balanced reversal",
    )
    require(
        any(e.get("publishedAt") is None for e in final["events"]),
        "Restored writer must keep new delivery fenced",
    )
    result = {
        "project": project,
        "images": images,
        "target_name": target_name,
        "target_lsn": target_lsn,
        "backup_seconds": backup_seconds,
        "backup_manifest_sha256": manifest_hash,
        "live_write_progress": [progress_before, progress_after],
        "archive_sha256": {
            line.split()[1].removeprefix("/archive/"): line.split()[0]
            for line in archive_hashes
        },
        "restore_seconds": restore_seconds,
        "table_sha256_expected": expected,
        "table_sha256_restored": actual,
        "source_after_target_table_sha256": source_after_target,
        "missing_wal_rejected": True,
        "missing_wal_exit_code": negative_info["State"]["ExitCode"],
        "source_post_target_refund_minor": 100,
        "restored_pre_refund_minor": payment["amountRefunded"],
        "restored_payment_journals_before_write": len(inspection["journals"]),
        "restored_payment_journals_after_write": len(final["journals"]),
        "journals_before_write": inspection["journals"],
        "journals_after_write": final["journals"],
        "exact_replays": len(replays),
        "replays": replays,
        "restored_delivery_fenced": True,
        "requests": records,
        "limits": "Two pre-target synthetic payments; one live-write overlap; same-host archive. Restored consumers/outbox fenced. No failover, production retention, RPO/RTO, scale or external-provider reconciliation qualification.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        "Online physical backup, named-point recovery and missing-WAL negative control passed"
    )


if __name__ == "__main__":
    main()
