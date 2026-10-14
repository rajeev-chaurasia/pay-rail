#!/usr/bin/env python3
"""Observed infrastructure faults on an owned cloud simulation, with no dumps."""

import argparse
from datetime import datetime, timezone
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
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("payrail-qual-") or not 1 <= args.rounds <= 5:
        parser.error("Owned bounded simulation required")
    names = {
        role: args.project + "-" + role + "-1"
        for role in ("postgres", "redis", "kafka", "app")
    }
    for name in names.values():
        info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        if info["Config"]["Labels"]["com.docker.compose.project"] != args.project:
            raise ValueError("Refuse to interrupt a foreign service")
    records = []
    actions = []

    def docker(*command):
        return subprocess.run(
            ["docker", *command], capture_output=True, check=True, timeout=90
        )

    def call(method, path, body=None, key=None, expected=200):
        headers = {
            "Authorization": "Bearer pr_test_demo",
            "Content-Type": "application/json",
            "PayRail-Version": "2026-01-01",
        }
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(
            "http://10.240.0.10:18080" + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        if status != expected:
            raise ValueError("Unexpected recovery status: " + str(status))
        return status, raw, json.loads(raw)

    def wait(probe, description):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                if probe():
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
                pass
            time.sleep(1)
        raise ValueError("Recovery timed out: " + description)

    def inject(service, command):
        began = datetime.now(timezone.utc).isoformat()
        before = json.loads(docker("inspect", names[service]).stdout)[0]["State"]
        docker(*command, names[service])
        after = json.loads(docker("inspect", names[service]).stdout)[0]["State"]
        if not before["Running"] or after["Running"]:
            raise ValueError("Fault boundary was not observed")
        actions.append(
            {
                "service": service,
                "action": command[0],
                "started_at": began,
                "before_running": before["Running"],
                "after_running": after["Running"],
                "exit_code": after["ExitCode"],
            }
        )

    for index in range(args.rounds):
        run = "cloud-crash-" + uuid.uuid4().hex
        created = call(
            "POST",
            "/v1/payment_intents",
            {"amount": 432, "currency": "usd", "captureMethod": "automatic"},
            run + "-create",
            201,
        )
        path = "/v1/payment_intents/" + created[2]["id"]
        started = time.monotonic()
        try:
            inject("kafka", ("stop", "--timeout", "5"))
            confirmation = call(
                "POST", path + "/confirm", key=run + "-confirm", expected=202
            )
            if (
                confirmation[2]["status"] != "processing"
                or call("GET", path + "/inspect")[2]["journals"]
            ):
                raise ValueError(
                    "Committed provider command must remain pending before faults"
                )
            inject("redis", ("stop", "--timeout", "5"))
            call(
                "POST",
                "/v1/payment_intents",
                {"amount": 123, "currency": "usd"},
                run + "-redis-rejected",
                503,
            )
            inject("app", ("kill", "--signal", "KILL"))
            inject("postgres", ("kill", "--signal", "KILL"))
        finally:
            docker("start", names["postgres"], names["redis"], names["kafka"])
            wait(
                lambda: subprocess.run(
                    [
                        "docker",
                        "exec",
                        names["postgres"],
                        "pg_isready",
                        "-U",
                        "payrail",
                    ],
                    capture_output=True,
                ).returncode
                == 0,
                "database",
            )
            docker("start", names["app"])

        def drained():
            view = call("GET", path + "/inspect")[2]
            return len(view["journals"]) == 1 and all(
                e.get("publishedAt") for e in view["events"]
            )

        wait(drained, "settlement and outbox drain")
        replay = call("POST", path + "/confirm", key=run + "-confirm", expected=202)
        if replay[:2] != confirmation[:2]:
            raise ValueError("Stored confirmation replay changed")
        final = call("GET", path + "/inspect")[2]
        payment = call("GET", path)[2]
        if (
            payment["status"] != "succeeded"
            or len(final["providerOperations"]) != 1
            or not final["journals"][0]["balanced"]
        ):
            raise ValueError("Duplicate or incorrect recovered monetary effect")
        records.append(
            {
                "round": index,
                "recovery_seconds": time.monotonic() - started,
                "inspection": final,
                "status": payment["status"],
                "captured_minor": payment["amountReceived"],
                "exact_confirm_replay": True,
            }
        )
        args.output.write_text(
            json.dumps(
                {
                    "observed_fault_actions": len(actions),
                    "actions": actions,
                    "rounds": records,
                    "limits": "Five deterministic combined infrastructure schedules on synthetic provider operations. Not a million crashes; database durability/ledger checks require separate snapshot reconciliation.",
                },
                indent=2,
            )
            + "\n"
        )
    print(
        "Observed "
        + str(len(actions))
        + " infrastructure faults; all recovered unique balanced settlements"
    )


if __name__ == "__main__":
    main()
