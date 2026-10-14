#!/usr/bin/env python3
"""Check retained PITR observations; hashes do not authenticate test execution."""

import argparse
import json
import math
from pathlib import Path
import re


TABLES = {
    "api_keys",
    "flyway_schema_history",
    "idempotency_records",
    "ledger_entries",
    "ledger_transactions",
    "migration_checkpoints",
    "outbox_events",
    "payment_intents",
    "payment_intents_v2",
    "processed_events",
    "refunds",
    "simulated_provider_operations",
    "tenants",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_journals(journals, expected_count):
    require(len(journals) == expected_count, "Journal count differs from entries")
    require(
        len({j["id"] for j in journals}) == expected_count
        and len({j["effectKey"] for j in journals}) == expected_count,
        "Duplicate monetary effect",
    )
    for journal in journals:
        entries = journal["entries"]
        require(len(entries) >= 2, "Incomplete journal")
        for entry in entries:
            require(
                type(entry["debit"]) is int
                and type(entry["credit"]) is int
                and entry["debit"] >= 0
                and entry["credit"] >= 0
                and (entry["debit"] > 0) != (entry["credit"] > 0),
                "Invalid money entry",
            )
        debits = sum(e["debit"] for e in entries)
        credits = sum(e["credit"] for e in entries)
        require(
            debits == credits == journal["debitTotal"] == journal["creditTotal"]
            and journal["posted"] is True
            and journal["balanced"] is True,
            "Unbalanced restored journal",
        )


def validate(data):
    for field in (
        "source_post_target_refund_minor",
        "restored_pre_refund_minor",
        "restored_payment_journals_before_write",
        "restored_payment_journals_after_write",
    ):
        require(type(data[field]) is int, "Invalid integer observation: " + field)
    for field in ("backup_seconds", "restore_seconds"):
        number = data[field]
        require(
            type(number) in (int, float) and math.isfinite(number) and number > 0,
            "Invalid duration: " + field,
        )
    require(data["target_name"] == "payrail_before_refund", "Wrong recovery target")
    require(
        re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", data["target_lsn"]) is not None,
        "Invalid target LSN",
    )
    images = data["images"]
    require(
        set(images) == {"app", "restored_app", "postgres", "restored", "negative"},
        "Missing runtime identity",
    )
    require(
        all(v.startswith("sha256:") and digest(v[7:]) for v in images.values()),
        "Invalid runtime identity",
    )
    require(
        images["app"] == images["restored_app"]
        and images["postgres"] == images["restored"] == images["negative"],
        "Source and restore images must match",
    )
    require(digest(data["backup_manifest_sha256"]), "Invalid backup manifest hash")
    require(
        len(data["live_write_progress"]) == 2 and all(data["live_write_progress"]),
        "Missing backup/write overlap",
    )
    archived = data["archive_sha256"]
    require(
        archived
        and all(
            re.fullmatch(r"[0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?", k) and digest(v)
            for k, v in archived.items()
        ),
        "Invalid archive inventory",
    )
    expected = data["table_sha256_expected"]
    restored = data["table_sha256_restored"]
    later = data["source_after_target_table_sha256"]
    require(
        TABLES <= set(expected) and set(expected) == set(restored) == set(later),
        "Incomplete table inventory",
    )
    require(
        all(
            digest(v)
            for inventory in (expected, restored, later)
            for v in inventory.values()
        ),
        "Invalid table hash",
    )
    require(expected == restored, "Restored tables differ from target")
    require(
        all(
            expected[t] != later[t]
            for t in (
                "payment_intents",
                "refunds",
                "ledger_entries",
                "ledger_transactions",
                "idempotency_records",
            )
        ),
        "Post-target mutations must differ from restored target",
    )
    require(
        data["missing_wal_rejected"] is True
        and type(data["missing_wal_exit_code"]) is int
        and data["missing_wal_exit_code"] > 0,
        "Missing-WAL negative control did not fail",
    )
    require(
        data["restored_delivery_fenced"] is True, "Restored delivery must remain fenced"
    )
    require(
        data["source_post_target_refund_minor"] == 100
        and data["restored_pre_refund_minor"] == 0,
        "Wrong refund state at recovery target",
    )
    require(
        data["restored_payment_journals_before_write"] == 1
        and data["restored_payment_journals_after_write"] == 2,
        "Duplicate or missing journal effects",
    )
    validate_journals(data["journals_before_write"], 1)
    validate_journals(data["journals_after_write"], 2)
    require(
        data["journals_before_write"][0] in data["journals_after_write"],
        "Restore must retain the original immutable settlement",
    )
    replays = data["replays"]
    require(
        type(data["exact_replays"]) is int
        and data["exact_replays"] == len(replays) == 3,
        "Replay count mismatch",
    )
    require(
        {r["operation"] for r in replays} == {"create", "confirm", "refund"},
        "Missing operation replay",
    )
    for replay in replays:
        require(
            replay["original_status"]
            == replay["replayed_status"]
            == {"create": 201, "confirm": 202, "refund": 200}[replay["operation"]],
            "Replay HTTP status mismatch",
        )
        require(
            digest(replay["original_sha256"])
            and replay["original_sha256"] == replay["replayed_sha256"],
            "Replay body mismatch",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path", nargs="?", type=Path, default=Path("evidence/flows/postgres-pitr.json")
    )
    args = parser.parse_args()
    validate(json.loads(args.path.read_text()))
    print("PITR table, replay, archive and negative-control observations validated")


if __name__ == "__main__":
    main()
