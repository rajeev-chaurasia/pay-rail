#!/usr/bin/env python3
"""Exercise real HTTP lifecycle and contract flows with synthetic local data."""

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:18080")
    parser.add_argument("--output", type=Path, default=Path("evidence/flows/http.json"))
    args = parser.parse_args()
    key = "flow-" + uuid.uuid4().hex
    observations = []

    def call(
        method,
        path,
        body=None,
        idem=None,
        status=200,
        version="2026-01-01",
        auth="pr_test_demo",
    ):
        headers = {"Content-Type": "application/json", "PayRail-Version": version}
        if auth is not None:
            headers["Authorization"] = "Bearer " + auth
        if idem:
            headers["Idempotency-Key"] = idem
        req = urllib.request.Request(
            args.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                actual = r.status
                raw = r.read()
                data = json.loads(raw)
        except urllib.error.HTTPError as e:
            actual = e.code
            raw = e.read()
            data = json.loads(raw)
        observations.append(
            {
                "method": method,
                "path": path,
                "expected": status,
                "actual": actual,
                "duration_ms": (time.monotonic() - started) * 1000,
            }
        )
        if actual != status:
            raise AssertionError((method, path, status, actual, data))
        return data, raw

    call("GET", "/v1/payment_intents", auth=None, status=401)
    call("GET", "/v1/payment_intents", auth="invalid", status=401)
    call(
        "POST",
        "/v1/payment_intents",
        {"amount": 0, "currency": "usd"},
        key + "-invalid",
        status=400,
    )
    call(
        "POST",
        "/v1/payment_intents",
        {"amount": 100, "currency": "usd"},
        key + "-version",
        version="unsupported",
        status=400,
    )
    body = {"amount": 1000, "currency": "usd", "captureMethod": "manual"}
    manual, original = call("POST", "/v1/payment_intents", body, key, status=201)
    replay, replayed = call("POST", "/v1/payment_intents", body, key, status=201)
    assert original == replayed and manual["id"] == replay["id"]
    call("POST", "/v1/payment_intents", {**body, "amount": 1001}, key, status=409)
    path = "/v1/payment_intents/" + manual["id"]
    call("POST", path + "/confirm", idem=key + "-confirm", status=202)
    call("POST", path + "/capture", {"amount": 999}, key + "-partial", status=400)
    captured, _ = call("POST", path + "/capture", {"amount": 1000}, key + "-capture")
    assert captured["status"] == "succeeded" and captured["amountReceived"] == 1000
    call(
        "POST", path + "/capture", {"amount": 1000}, key + "-capture-again", status=409
    )
    call("POST", path + "/cancel", idem=key + "-cancel-after", status=409)
    old, _ = call("GET", path, version="2025-01-01")
    new, _ = call("GET", path)
    assert old["state"] == new["status"] and old["version"] == new["version"]
    refund, original = call("POST", path + "/refunds", {"amount": 100}, key + "-refund")
    _, replayed = call("POST", path + "/refunds", {"amount": 100}, key + "-refund")
    assert original == replayed
    call("POST", path + "/refunds", {"amount": 901}, key + "-excess", status=400)
    call("POST", path + "/refunds", {"amount": 900}, key + "-rest")
    final, _ = call("GET", path)
    assert final["status"] == "refunded" and final["amountRefunded"] == 1000
    call("POST", path + "/refunds", {"amount": 1}, key + "-terminal", status=409)
    inspected, _ = call("GET", path + "/inspect")
    assert len(inspected["journals"]) == 3 and all(
        j["balanced"] for j in inspected["journals"]
    )
    canceled, _ = call(
        "POST", "/v1/payment_intents", body, key + "-canceled", status=201
    )
    canceled_path = "/v1/payment_intents/" + canceled["id"]
    call("POST", canceled_path + "/cancel", idem=key + "-cancel")
    call("POST", canceled_path + "/confirm", idem=key + "-cancel-confirm", status=409)
    authorized, _ = call(
        "POST", "/v1/payment_intents", body, key + "-authorized", status=201
    )
    authorized_path = "/v1/payment_intents/" + authorized["id"]
    call("POST", authorized_path + "/confirm", idem=key + "-authorize", status=202)
    call("POST", authorized_path + "/cancel", idem=key + "-authorize-cancel")
    automatic, _ = call(
        "POST",
        "/v1/payment_intents",
        {"amount": 1000, "currency": "jpy", "captureMethod": "automatic"},
        key + "-automatic",
        status=201,
    )
    automatic_path = "/v1/payment_intents/" + automatic["id"]
    call(
        "POST", automatic_path + "/confirm", idem=key + "-automatic-confirm", status=202
    )
    for _ in range(60):
        completed, _ = call("GET", automatic_path)
        if completed["status"] == "succeeded":
            break
        time.sleep(0.5)
    assert completed["status"] == "succeeded" and completed["amountReceived"] == 1000
    inspect, _ = call("GET", automatic_path + "/inspect")
    assert len(inspect["journals"]) == len(inspect["providerOperations"]) == 1
    page, _ = call("GET", "/v1/payment_intents?limit=2")
    assert len(page["data"]) == 2
    next_page, _ = call(
        "GET", "/v1/payment_intents?limit=2&after=" + page["next_cursor"]
    )
    assert not {p["id"] for p in page["data"]} & {p["id"] for p in next_page["data"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "run_id": key,
                "url": args.url,
                "observations": observations,
                "checks": "HTTP contracts, saved bytes, terminal state, balances, provider completion and pagination passed",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Real HTTP flow smoke passed: {len(observations)} requests; {args.output}")


if __name__ == "__main__":
    main()
