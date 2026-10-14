#!/usr/bin/env python3
"""Independently recompute local load metrics and financial snapshot invariants."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

EXPECTED = {
    "create": 201,
    "create_replay": 201,
    "fingerprint_conflict": 409,
    "confirm": 202,
    "cancel_created": 200,
    "confirm_canceled": 409,
    "cancel_authorized": 200,
    "capture_canceled": 409,
    "capture": 200,
    "legacy_read": 200,
    "current_read": 200,
    "partial_refund": 200,
    "refund_replay": 200,
    "full_refund": 200,
    "final_read": 200,
    "provider_poll": 200,
}
COUNTERS = [
    "observed_requests",
    "unexpected_responses",
    "created_intents",
    "accepted_mutations",
    "rate_limit_rejections",
    "started_workflows",
    "completed_workflows",
    "dropped_iterations",
]


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def load_metrics(path):
    totals = Counter()
    statuses = Counter()
    durations = []
    operations = defaultdict(list)
    failed_checks = 0
    checks = 0
    bad = []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            point = json.loads(line)
            if point.get("type") != "Point":
                continue
            metric = point["metric"]
            data = point["data"]
            value = data["value"]
            tags = data.get("tags", {})
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Nonfinite raw metric")
            if metric in COUNTERS:
                if value < 0 or value != int(value):
                    raise ValueError("Invalid counter sample")
                totals[metric] += value
            if metric == "checks":
                if value not in [0, 1]:
                    raise ValueError("Invalid check sample")
                checks += 1
                failed_checks += int(value != 1)
            if metric == "http_req_duration":
                if value < 0:
                    raise ValueError("Negative request duration")
                durations.append(value)
                name = tags.get("name")
                status = int(tags.get("status", 0))
                operations[name].append(value)
                statuses[str(status)] += 1
                if name not in EXPECTED:
                    bad.append(f"Unknown request name {name}")
                elif status != EXPECTED[name]:
                    bad.append(f"{name}: unexpected HTTP {status}")
    return {
        "totals": totals,
        "statuses": statuses,
        "durations": durations,
        "operations": operations,
        "checks": checks,
        "failed_checks": failed_checks,
        "unexpected_http": bad,
    }


def require(condition, message, errors):
    if not condition:
        errors.append(message)


def financial_invariants(snapshot):
    errors = []
    payments = {p["id"]: p for p in snapshot["payments"]}
    journal_ids = set()
    effects = set()
    entries = defaultdict(list)
    per_payment = defaultdict(list)
    require(len(payments) == len(snapshot["payments"]), "duplicate payment IDs", errors)
    require(
        len({e["id"] for e in snapshot["entries"]}) == len(snapshot["entries"]),
        "duplicate entry ID",
        errors,
    )
    require(
        len({r["id"] for r in snapshot["refunds"]}) == len(snapshot["refunds"]),
        "duplicate refund ID",
        errors,
    )
    refund_by_id = {r["id"]: r for r in snapshot["refunds"]}
    for entry in snapshot["entries"]:
        entries[entry["ledger_transaction_id"]].append(entry)
        require(
            (entry["debit"] > 0 and entry["credit"] == 0)
            or (entry["credit"] > 0 and entry["debit"] == 0),
            "invalid entry side/amount",
            errors,
        )
    for journal in snapshot["journals"]:
        jid = journal["id"]
        pid = journal["payment_intent_id"]
        rows = entries[jid]
        require(jid not in journal_ids, "duplicate journal ID", errors)
        journal_ids.add(jid)
        require(
            journal["effect_key"] not in effects, "duplicate business effect", errors
        )
        effects.add(journal["effect_key"])
        require(pid in payments, "journal references absent payment", errors)
        require(
            journal["posted"]
            and len(rows) >= 2
            and sum(r["debit"] for r in rows) == sum(r["credit"] for r in rows),
            "unposted/unbalanced journal",
            errors,
        )
        if pid in payments:
            require(
                journal["currency"] == payments[pid]["currency"],
                "journal currency differs",
                errors,
            )
        effect = journal["effect_key"]
        capture = effect == "capture:" + pid
        refund = (
            refund_by_id.get(effect.removeprefix("refund:"))
            if effect.startswith("refund:")
            else None
        )
        require(
            capture or (refund and refund["payment_intent_id"] == pid),
            "unknown journal business effect",
            errors,
        )
        debit_account = "provider_clearing" if capture else "merchant_payable"
        credit_account = "merchant_payable" if capture else "provider_clearing"
        require(
            all(
                (r["debit"] > 0 and r["account"] == debit_account)
                or (r["credit"] > 0 and r["account"] == credit_account)
                for r in rows
            ),
            "journal account direction differs",
            errors,
        )
        per_payment[pid].append(journal)
    require(set(entries) <= journal_ids, "orphan ledger entry", errors)
    refund_totals = Counter()
    for refund in snapshot["refunds"]:
        pid = refund["payment_intent_id"]
        refund_totals[pid] += refund["amount"]
        matches = [
            j for j in per_payment[pid] if j["effect_key"] == "refund:" + refund["id"]
        ]
        require(
            pid in payments
            and refund["amount"] > 0
            and refund["status"] == "succeeded",
            "invalid refund",
            errors,
        )
        require(len(matches) == 1, "refund journal missing or duplicate", errors)
        if matches:
            require(
                sum(e["debit"] for e in entries[matches[0]["id"]]) == refund["amount"],
                "refund posting amount differs",
                errors,
            )
    for pid, payment in payments.items():
        state = payment["status"]
        require(
            state
            in {
                "requires_confirmation",
                "processing",
                "authorized",
                "succeeded",
                "partially_refunded",
                "refunded",
                "canceled",
                "failed",
            },
            "unknown payment state",
            errors,
        )
        if state in {"requires_confirmation", "processing", "canceled", "failed"}:
            require(
                payment["amount_received"]
                == payment["amount_refunded"]
                == payment["amount_capturable"]
                == 0,
                "uncaptured state has money effects",
                errors,
            )
        if state == "authorized":
            require(
                payment["amount_capturable"] == payment["amount"]
                and payment["amount_received"] == payment["amount_refunded"] == 0,
                "authorization money differs",
                errors,
            )
        if state in {"succeeded", "partially_refunded", "refunded"}:
            require(
                payment["amount_received"] == payment["amount"]
                and payment["amount_capturable"] == 0,
                "captured state money differs",
                errors,
            )
        if state == "partially_refunded":
            require(
                0 < payment["amount_refunded"] < payment["amount_received"],
                "invalid partial refund state",
                errors,
            )
        require(
            0
            <= payment["amount_refunded"]
            <= payment["amount_received"]
            <= payment["amount"],
            "money bounds violated",
            errors,
        )
        require(
            refund_totals[pid] == payment["amount_refunded"],
            "refund total differs",
            errors,
        )
        captures = [j for j in per_payment[pid] if j["effect_key"] == "capture:" + pid]
        require(
            len(captures) == (1 if payment["amount_received"] > 0 else 0),
            "capture effect count differs",
            errors,
        )
        if captures:
            require(
                sum(e["debit"] for e in entries[captures[0]["id"]])
                == payment["amount_received"],
                "capture posting differs",
                errors,
            )
        if payment["status"] == "canceled":
            require(not per_payment[pid], "canceled payment has journal", errors)
        if payment["status"] == "refunded":
            require(
                payment["amount_received"] == payment["amount_refunded"] > 0,
                "invalid fully refunded state",
                errors,
            )
        require(
            payment["status"] != "processing", "processing remained after drain", errors
        )
    providers = snapshot["providers"]
    require(
        len({p["payment_id"] for p in providers}) == len(providers),
        "duplicate provider operation",
        errors,
    )
    require(
        len({p["provider_reference"] for p in providers}) == len(providers),
        "duplicate provider reference",
        errors,
    )
    expected_provider = {
        pid
        for pid, p in payments.items()
        if p["capture_method"] == "automatic" and p["amount_received"] > 0
    }
    require(
        {p["payment_id"] for p in providers} == expected_provider,
        "provider operation count differs",
        errors,
    )
    events = defaultdict(list)
    require(
        len({e["id"] for e in snapshot["events"]}) == len(snapshot["events"]),
        "duplicate event ID",
        errors,
    )
    for event in snapshot["events"]:
        require(event["aggregate_id"] in payments, "orphan event", errors)
        events[event["aggregate_id"]].append(event["aggregate_sequence"])
        require(event["published_at"] is not None, "event not drained", errors)
    for pid, p in payments.items():
        require(
            sorted(events[pid]) == list(range(1, p["version"] + 1)),
            "event sequence missing or duplicate",
            errors,
        )
    targets = {p["source_id"]: p for p in snapshot["migration"]}
    require(
        len(targets) == len(snapshot["migration"]),
        "duplicate migration target ID",
        errors,
    )
    require(set(targets) == set(payments), "migration missing or extra objects", errors)
    fields = {
        "amount": "amount_minor",
        "currency": "currency_code",
        "capture_method": "capture_method",
        "status": "lifecycle_status",
        "version": "source_version",
        "amount_capturable": "capturable_minor",
        "amount_received": "captured_minor",
        "amount_refunded": "refunded_minor",
        "metadata": "metadata",
        "created_at": "source_created_at",
        "updated_at": "source_updated_at",
    }
    for pid, p in payments.items():
        if pid in targets:
            require(
                all(p[a] == targets[pid][b] for a, b in fields.items()),
                "migration representation differs",
                errors,
            )
    return sorted(set(errors))


def validate(directory):
    hashes = json.loads((directory / "checksums.json").read_text())
    required = {
        "manifest.json",
        "raw.json.gz",
        "summary.json",
        "drain.json",
        "resources.jsonl",
        "k6.log",
    }
    if not required <= set(hashes):
        raise ValueError("Missing required artifact")
    snapshot_name = (
        "snapshot.json.gz"
        if (directory / "snapshot.json.gz").exists()
        else "snapshot.json"
    )
    if snapshot_name not in hashes:
        raise ValueError("Accounting snapshot is not sealed")
    for name, digest in hashes.items():
        if Path(name).name != name:
            raise ValueError("Invalid artifact name")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Checksum differs: {name}")
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    if (directory / "snapshot.json.gz").exists():
        with gzip.open(directory / "snapshot.json.gz", "rt") as handle:
            snapshot = json.load(handle)
    else:
        snapshot = json.loads((directory / "snapshot.json").read_text())
    raw = load_metrics(directory / "raw.json.gz")
    if manifest["schema"] != "payrail-performance-v1":
        raise ValueError("Unknown artifact schema")
    counters = raw["totals"]
    consistency = []
    for name in COUNTERS:
        saved = (
            summary.get("metrics", {}).get(name, {}).get("values", {}).get("count", 0)
        )
        require(
            saved == counters[name],
            f"{name} summary differs from raw observations",
            consistency,
        )
    require(
        len(raw["durations"]) == counters["observed_requests"],
        "HTTP sample count differs from custom request count",
        consistency,
    )
    require(
        counters["created_intents"]
        <= len(snapshot["payments"])
        <= counters["started_workflows"],
        "committed intents exceed started workflows or acknowledged creates exceed commits",
        consistency,
    )
    for name, fraction in [("p(95)", 0.95), ("p(99)", 0.99)]:
        saved = summary["metrics"]["http_req_duration"]["values"][name]
        require(
            abs(saved - percentile(raw["durations"], fraction)) < 0.01,
            f"{name} differs from raw samples",
            consistency,
        )
    if consistency:
        raise ValueError("; ".join(consistency))
    invariants = financial_invariants(snapshot)
    limits = manifest["limits"]
    p95 = percentile(raw["durations"], 0.95)
    p99 = percentile(raw["durations"], 0.99)
    qualification = []
    if manifest["profile"] in {"mixed", "mixed-baseline"}:
        required_mix = {
            "confirm",
            "capture",
            "partial_refund",
            "full_refund",
            "cancel_created",
            "cancel_authorized",
            "provider_poll",
        }
        require(
            required_mix <= set(raw["operations"]),
            "declared mixed workload did not exercise every planned lifecycle",
            qualification,
        )
    require(
        len(snapshot["payments"]) == counters["created_intents"],
        "committed creates lack an acknowledged success response",
        qualification,
    )
    resource_count = sum(1 for _ in (directory / "resources.jsonl").open())
    require(resource_count > 0, "no resource observations", qualification)
    drain = json.loads((directory / "drain.json").read_text())
    require(
        bool(drain) and drain[-1]["pending_events"] == drain[-1]["processing"] == 0,
        "drain deadline exceeded",
        qualification,
    )
    require(not raw["unexpected_http"], "unexpected HTTP outcomes", qualification)
    require(not raw["failed_checks"], "failed semantic/status checks", qualification)
    require(
        counters["rate_limit_rejections"] == 0,
        "rate-limit rejection during load",
        qualification,
    )
    require(
        counters["dropped_iterations"] == 0, "offered iterations dropped", qualification
    )
    require(
        counters["completed_workflows"] == counters["started_workflows"],
        "incomplete workflows",
        qualification,
    )
    require(
        abs(
            counters["started_workflows"]
            + counters["dropped_iterations"]
            - manifest["expected_iterations"]
        )
        <= 1,
        "offered schedule not delivered",
        qualification,
    )
    require(
        p95 < limits["p95_ms"] and p99 < limits["p99_ms"],
        "latency budget exceeded",
        qualification,
    )
    require(
        manifest["exit_code"] == 0, "k6 threshold or execution failure", qualification
    )
    require(not invariants, "post-run invariant failure", qualification)
    operations = {
        name: {
            "requests": len(values),
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99),
            "max_ms": max(values),
        }
        for name, values in sorted(raw["operations"].items())
    }
    return {
        "run_id": manifest["run_id"],
        "profile": manifest["profile"],
        "nominal_rate": manifest["rate"],
        "duration_seconds": manifest["duration_seconds"],
        "qualified": not qualification,
        "qualification_failures": qualification,
        "invariant_failures": invariants,
        "offered_iterations": manifest["expected_iterations"],
        "started_workflows": counters["started_workflows"],
        "completed_workflows": counters["completed_workflows"],
        "dropped_iterations": counters["dropped_iterations"],
        "requests": len(raw["durations"]),
        "http_statuses": dict(raw["statuses"]),
        "created_intents": len(snapshot["payments"]),
        "acknowledged_created_intents": counters["created_intents"],
        "committed_creates_without_acknowledgement": len(snapshot["payments"])
        - counters["created_intents"],
        "financial_invariant_failures": [
            e
            for e in invariants
            if e not in {"event not drained", "processing remained after drain"}
        ],
        "drain_seconds": (
            __import__("datetime").datetime.fromisoformat(drain[-1]["time"])
            - __import__("datetime").datetime.fromisoformat(drain[0]["time"])
        ).total_seconds(),
        "created_intents_per_offered_second": len(snapshot["payments"])
        / manifest["duration_seconds"],
        "accepted_mutating_http_responses_including_replays": counters[
            "accepted_mutations"
        ],
        "latency_ms": {
            "p50": percentile(raw["durations"], 0.5),
            "p95": p95,
            "p99": p99,
            "max": max(raw["durations"], default=0),
        },
        "operations": operations,
        "journals": len(snapshot["journals"]),
        "refunds": len(snapshot["refunds"]),
        "outbox_events": len(snapshot["events"]),
        "published_events": sum(
            e["published_at"] is not None for e in snapshot["events"]
        ),
        "pending_events_at_snapshot": sum(
            e["published_at"] is None for e in snapshot["events"]
        ),
        "failed_checks": raw["failed_checks"],
        "resource_observations": sum(1 for _ in (directory / "resources.jsonl").open()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path("evidence/performance")
    )
    parser.add_argument(
        "--allow-unqualified",
        action="store_true",
        help="Accept internally valid capacity-boundary observations; monetary invariant failures still fail.",
    )
    args = parser.parse_args()
    directories = (
        [args.root]
        if (args.root / "manifest.json").exists()
        else sorted(
            path
            for path in args.root.iterdir()
            if path.is_dir() and (path / "manifest.json").exists()
        )
    )
    if not directories:
        raise SystemExit("No measured performance artifacts found")
    reports = []
    for directory in directories:
        report = validate(directory)
        reports.append(report)
        directory.joinpath("report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        print(
            f"{report['profile']}: qualified={report['qualified']}, created={report['created_intents']}, requests={report['requests']}, p95={report['latency_ms']['p95']:.2f}ms, p99={report['latency_ms']['p99']:.2f}ms, invariant_failures={len(report['invariant_failures'])}"
        )
    if len(directories) > 1:
        args.root.joinpath("reports.json").write_text(
            json.dumps(reports, indent=2, sort_keys=True) + "\n"
        )

    if any(r["financial_invariant_failures"] for r in reports):
        raise SystemExit("Financial invariant failure")
    if not args.allow_unqualified and any(not r["qualified"] for r in reports):
        raise SystemExit("One or more runs did not meet declared capacity budgets")


if __name__ == "__main__":
    main()
