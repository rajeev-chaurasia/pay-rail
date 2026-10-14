#!/usr/bin/env python3
"""Render measured README results from independently validated reports."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = "<!-- performance-results:start -->"
END = "<!-- performance-results:end -->"


def section():
    reports = json.loads((ROOT / "evidence/performance/reports.json").read_text())
    rows = [
        "Measured on the shared local Docker host. Latency is per completed HTTP request; failed and dropped work is reported separately.",
        "",
        "| Study | Observed work | p95 / p99 | Budget result |",
        "| --- | --- | --- | --- |",
    ]
    for report in reports:
        label = report["profile"]
        if label == "smoke":
            continue
        work = f"{report['acknowledged_created_intents']:,} acknowledged creates"
        if "mixed" in label:
            work = f"{report['completed_workflows']:,} workflows / {report['requests']:,} HTTP requests"
        latency = (
            f"{report['latency_ms']['p95']:.1f} / {report['latency_ms']['p99']:.1f} ms"
        )
        result = "Pass" if report["qualified"] else "Not qualified"
        link = f"evidence/performance/{report['run_id']}/report.json"
        rows.append(f"| [{label}]({link}) | {work} | {latency} | {result} |")
    baseline = []
    for label in ["baseline-a", "baseline-b"]:
        candidates = [r for r in reports if r["profile"] == label and r["qualified"]]
        if not candidates:
            raise ValueError(
                "A passing artifact is required for each baseline narrative"
            )
        baseline.append(candidates[-1])
    mixed = [r for r in reports if r["profile"] == "mixed-baseline" and r["qualified"]][
        -1
    ]
    stress = [r for r in reports if r["profile"] == "stress"][-1]
    baseline_text = " and ".join(
        f"{r['nominal_rate']} arrivals/s for {r['duration_seconds']} seconds"
        for r in baseline
    )
    rows += [
        "",
        f"Passing create baselines: {baseline_text}. The corrected",
        f"{mixed['nominal_rate']} workflow arrivals/s mixed run completed {mixed['completed_workflows']:,} workflows, {mixed['requests']:,} HTTP requests,",
        f"{mixed['journals']:,} balanced journals and {mixed['refunds']:,} refunds. Failed higher-rate studies remain retained.",
        f"The stress snapshot recorded {stress['pending_events_at_snapshot']:,} pending events at its bounded drain deadline.",
        "None of these studies establishes the 25K/s target. See",
        "[the method, failed runs and limits](docs/performance.md).",
    ]
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "README.md"
    old = path.read_text()
    before, remainder = old.split(START, 1)
    _, after = remainder.split(END, 1)
    updated = before + START + "\n" + section() + "\n" + END + after
    if args.check:
        if old != updated:
            raise SystemExit("README performance numbers differ from validated reports")
        print("README performance numbers match validated reports")
    else:
        path.write_text(updated)


if __name__ == "__main__":
    main()
