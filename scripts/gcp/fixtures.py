#!/usr/bin/env python3
"""Create synthetic fault fixtures on the owned benchmark, never a real provider."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from pathlib import Path
import subprocess
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("provision", "prepare"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/fault-fixtures.json")
    )
    parser.add_argument("--count", type=int, default=4096)
    parser.add_argument("--defer-capture", action="store_true")
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,64}", args.run):
        parser.error("Unique fixture run identity required")
    if not args.project.startswith("payrail-qual-") or not 1 <= args.count <= 4096:
        parser.error("Owned bounded qualification project required")
    tenant = "tenant_faults"
    if args.action == "provision":
        if not args.key_file.exists():
            args.key_file.write_text("pr_test_fault_" + uuid.uuid4().hex + "\n")
            args.key_file.chmod(0o600)
        digest = hashlib.sha256(
            (
                "local-development-pepper-change-me:"
                + args.key_file.read_text().strip()
            ).encode()
        ).hexdigest()
        container = args.project + "-postgres-1"
        info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
        if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
            raise ValueError("Foreign PostgreSQL container")
        statement = f"insert into tenants(id,name) values ('{tenant}','Synthetic fault campaign') on conflict do nothing; insert into api_keys(tenant_id,key_hash,label) values ('{tenant}','{digest}','qualification fixture') on conflict(key_hash) do nothing;"
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "payrail",
                "-d",
                "payrail",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input=statement,
            text=True,
            check=True,
        )
        return
    key = args.key_file.read_text().strip()

    def call(path, body, idem, expected):
        request = urllib.request.Request(
            "http://10.240.0.10:18080" + path,
            data=None if body is None else json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "PayRail-Version": "2026-01-01",
                "Idempotency-Key": idem,
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            if response.status != expected:
                raise ValueError("Unexpected fixture status")
            return raw, json.loads(raw)

    def prepare(index):
        create_key = args.run + "-create-" + str(index)
        capture_key = args.run + "-capture-" + str(index)
        _, payment = call(
            "/v1/payment_intents",
            {"amount": 1000, "currency": "usd", "captureMethod": "manual"},
            create_key,
            201,
        )
        path = "/v1/payment_intents/" + payment["id"]
        call(path + "/confirm", None, args.run + "-confirm-" + str(index), 202)
        if args.defer_capture:
            return {
                "id": payment["id"],
                "create_key": create_key,
                "capture_key": capture_key,
                "capture_sha256": "",
            }
        raw, captured = call(path + "/capture", {"amount": 1000}, capture_key, 200)
        if captured["status"] != "succeeded" or captured["amountReceived"] != 1000:
            raise ValueError("Fixture did not capture")
        return {
            "id": payment["id"],
            "create_key": create_key,
            "capture_key": capture_key,
            "capture_sha256": hashlib.sha256(raw).hexdigest(),
        }

    with ThreadPoolExecutor(max_workers=32) as pool:
        fixtures = list(pool.map(prepare, range(args.count)))
    args.output.write_text(
        json.dumps(
            {"project": args.project, "tenant": tenant, "fixtures": fixtures}, indent=2
        )
        + "\n"
    )
    print("Prepared " + str(len(fixtures)) + " synthetic captured payment fixtures")


if __name__ == "__main__":
    main()
