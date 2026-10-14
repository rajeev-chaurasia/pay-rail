#!/usr/bin/env python3
"""Verify stored bytes and fingerprints across a local runtime upgrade."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import uuid


def image():
    return subprocess.check_output(
        ["docker", "inspect", "--format", "{{.Image}}", "payrail-app-1"], text=True
    ).strip()


def request(url, case):
    req = urllib.request.Request(
        url + "/v1/payment_intents",
        json.dumps(case["request"]).encode(),
        {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
            "Idempotency-Key": case["key"],
            "PayRail-Version": case["version"],
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.status, response.read().decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument(
        "--url", default=os.environ.get("PAYRAIL_URL", "http://localhost:18080")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evidence/qualification/compatibility.json")
    )
    args = parser.parse_args()
    if args.phase == "before":
        run = uuid.uuid4().hex
        cases = []
        for version in ["2025-01-01", "2026-01-01"]:
            for metadata in [
                {"nested": {"z": 2.0, "a": [1, True, None]}, "label": "synthetic café"},
                {"tiny": 0.00001, "zero": 0},
            ]:
                metadata["compatibility_run"] = run
                case = {
                    "key": "compat-" + uuid.uuid4().hex,
                    "version": version,
                    "request": {
                        "amount": 101,
                        "currency": "usd",
                        "captureMethod": "manual",
                        "metadata": metadata,
                    },
                }
                case["status"], case["wire_body"] = request(args.url, case)
                assert case["status"] == 201
                cases.append(case)
        report = {
            "run_id": run,
            "before_image": image(),
            "cases": cases,
            "after_verified": False,
        }
    else:
        report = json.loads(args.output.read_text())
        assert len(report["cases"]) == 4 and len(report["run_id"]) == 32
        for case in report["cases"]:
            status, body = request(args.url, case)
            assert status == case["status"] and body == case["wire_body"], (
                "Saved bytes/fingerprint changed"
            )
        assert all(c in "0123456789abcdef" for c in report["run_id"])
        query = (
            "select count(*) from payment_intents where tenant_id='tenant_demo' and metadata->>'compatibility_run'='"
            + report["run_id"]
            + "'"
        )
        count = int(
            subprocess.check_output(
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
                ],
                text=True,
            )
        )
        assert count == 4, "Duplicate committed create effect"
        report.update(
            {"after_image": image(), "after_verified": True, "committed_intents": count}
        )
        assert report["after_image"] != report["before_image"], (
            "Runtime image did not change"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Cross-runtime compatibility {args.phase}: four synthetic requests, both API contracts"
    )


if __name__ == "__main__":
    main()
