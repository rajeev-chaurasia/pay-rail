#!/usr/bin/env python3
"""Bounded broker-outage recovery check on the named local simulated stack."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url", default=os.environ.get("PAYRAIL_URL", "http://localhost:18080")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evidence/flows/kafka-recovery.json")
    )
    args = parser.parse_args()
    run = "broker-" + uuid.uuid4().hex
    records = []

    def call(method, path, body=None, key=None):
        headers = {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
        }
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(
            args.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            records.append({"method": method, "path": path, "status": response.status})
            return data

    created = call(
        "POST",
        "/v1/payment_intents",
        {"amount": 432, "currency": "usd", "captureMethod": "automatic"},
        run + "-create",
    )
    path = "/v1/payment_intents/" + created["id"]
    subprocess.run(
        ["docker", "stop", "--time", "5", "payrail-kafka-1"],
        check=True,
        capture_output=True,
    )
    try:
        response = call("POST", path + "/confirm", key=run + "-confirm")
        assert response["status"] == "processing"
        inspection = call("GET", path + "/inspect")
        assert not inspection["journals"]
        assert any(event.get("publishedAt") is None for event in inspection["events"])
        time.sleep(25)
        waiting = call("GET", path)
        assert waiting["status"] == "processing"
    finally:
        subprocess.run(
            ["docker", "start", "payrail-kafka-1"], check=True, capture_output=True
        )
    settled = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        settled = call("GET", path)
        inspection = call("GET", path + "/inspect")
        if settled["status"] == "succeeded" and all(
            e.get("publishedAt") for e in inspection["events"]
        ):
            break
        time.sleep(2)
    assert settled["status"] == "succeeded" and all(
        e.get("publishedAt") for e in inspection["events"]
    )
    replay = call("POST", path + "/confirm", key=run + "-confirm")
    assert replay["status"] == "processing"
    final = call("GET", path + "/inspect")
    assert len(final["journals"]) == len(final["providerOperations"]) == 1
    assert final["journals"][0]["balanced"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "run_id": run,
                "outage_wait_seconds": 25,
                "recovery_seconds": 180 - (deadline - time.monotonic()),
                "captured_minor": settled["amountReceived"],
                "journal_count": len(final["journals"]),
                "provider_operation_count": len(final["providerOperations"]),
                "events": final["events"],
                "requests": records,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "Kafka outage/recovery passed: committed processing intent recovered, one provider operation and one balanced journal"
    )


if __name__ == "__main__":
    main()
