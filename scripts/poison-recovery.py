#!/usr/bin/env python3
"""Observe acknowledged local Kafka quarantine and subsequent payment completion."""

import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid


def main():
    url = os.environ.get("PAYRAIL_URL", "http://localhost:18080")
    key = "poison-" + uuid.uuid4().hex
    payload = "{synthetic invalid json"
    offsets = subprocess.check_output(
        [
            "docker",
            "exec",
            "payrail-kafka-1",
            "/opt/kafka/bin/kafka-get-offsets.sh",
            "--bootstrap-server",
            "localhost:29092",
            "--topic",
            "payrail.payment-events.DLT",
            "--time",
            "-1",
        ],
        text=True,
        timeout=30,
    )
    offset = next(
        line.rsplit(":", 1)[1]
        for line in offsets.splitlines()
        if line.startswith("payrail.payment-events.DLT:0:")
    )
    began = time.monotonic()
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "payrail-kafka-1",
            "/opt/kafka/bin/kafka-console-producer.sh",
            "--bootstrap-server",
            "localhost:29092",
            "--topic",
            "payrail.payment-events",
            "--property",
            "parse.key=true",
            "--property",
            "key.separator=|",
        ],
        input=key + "|" + payload + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "payrail-kafka-1",
            "/opt/kafka/bin/kafka-console-consumer.sh",
            "--bootstrap-server",
            "localhost:29092",
            "--topic",
            "payrail.payment-events.DLT",
            "--partition",
            "0",
            "--offset",
            offset,
            "--max-messages",
            "1",
            "--timeout-ms",
            "60000",
            "--property",
            "print.key=true",
            "--property",
            "key.separator=|",
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=75,
    )
    assert result.stdout.strip() == key + "|" + payload, (
        "Quarantine did not preserve the poison fixture"
    )
    quarantine_seconds = time.monotonic() - began

    def request(method, path, body=None, suffix=""):
        headers = {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
        }
        if method == "POST":
            headers["Idempotency-Key"] = key + suffix
        req = urllib.request.Request(
            url + path,
            None if body is None else json.dumps(body).encode(),
            headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read())

    status, payment = request(
        "POST",
        "/v1/payment_intents",
        {"amount": 321, "currency": "usd", "captureMethod": "automatic"},
        "-create",
    )
    assert status == 201
    path = "/v1/payment_intents/" + payment["id"]
    assert request("POST", path + "/confirm", {}, "-confirm")[0] == 202
    for _ in range(120):
        payment = request("GET", path)[1]
        if payment["status"] == "succeeded":
            break
        time.sleep(0.5)
    assert payment["status"] == "succeeded", "Partition remained blocked"
    inspection = request("GET", path + "/inspect")[1]
    assert len(inspection["journals"]) == 1
    journal = inspection["journals"][0]
    assert journal["balanced"]
    report = {
        "scope": "One malformed synthetic Kafka record reaches acknowledged quarantine; a subsequent automatic payment completes",
        "quarantine_key": key,
        "quarantine_seconds": quarantine_seconds,
        "following_payment_status": payment["status"],
        "journal_count": len(inspection["journals"]),
        "balanced": journal["balanced"],
    }
    Path("evidence/qualification/poison-recovery.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        "Poison quarantine passed; subsequent automatic payment completed with one balanced journal"
    )


if __name__ == "__main__":
    main()
