import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "performance_validator", Path(__file__).with_name("validate.py")
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def snapshot():
    return {
        "payments": [
            {
                "id": "pi_1",
                "amount": 1000,
                "currency": "usd",
                "capture_method": "manual",
                "status": "succeeded",
                "version": 3,
                "amount_capturable": 0,
                "amount_received": 1000,
                "amount_refunded": 0,
                "metadata": {},
                "created_at": "t1",
                "updated_at": "t2",
            }
        ],
        "journals": [
            {
                "id": "j1",
                "payment_intent_id": "pi_1",
                "effect_key": "capture:pi_1",
                "currency": "usd",
                "posted": True,
            }
        ],
        "entries": [
            {
                "id": 1,
                "ledger_transaction_id": "j1",
                "account": "provider_clearing",
                "debit": 1000,
                "credit": 0,
            },
            {
                "id": 2,
                "ledger_transaction_id": "j1",
                "account": "merchant_payable",
                "debit": 0,
                "credit": 1000,
            },
        ],
        "refunds": [],
        "providers": [],
        "events": [
            {
                "id": f"e{i}",
                "aggregate_id": "pi_1",
                "aggregate_sequence": i,
                "published_at": "t3",
            }
            for i in range(1, 4)
        ],
        "migration": [
            {
                "source_id": "pi_1",
                "amount_minor": 1000,
                "currency_code": "usd",
                "capture_method": "manual",
                "lifecycle_status": "succeeded",
                "source_version": 3,
                "capturable_minor": 0,
                "captured_minor": 1000,
                "refunded_minor": 0,
                "metadata": {},
                "source_created_at": "t1",
                "source_updated_at": "t2",
            }
        ],
    }


class ValidatorAdversarialTests(unittest.TestCase):
    def test_valid_capture_has_no_failure(self):
        self.assertEqual(validator.financial_invariants(snapshot()), [])

    def test_duplicate_effect_is_rejected(self):
        data = snapshot()
        extra = copy.deepcopy(data["journals"][0])
        extra["id"] = "j2"
        data["journals"].append(extra)
        self.assertIn("duplicate business effect", validator.financial_invariants(data))

    def test_balanced_wrong_accounts_are_rejected(self):
        data = snapshot()
        data["entries"][0]["account"] = "merchant_payable"
        self.assertIn(
            "journal account direction differs", validator.financial_invariants(data)
        )

    def test_unknown_balanced_effect_is_rejected(self):
        data = snapshot()
        data["journals"][0]["effect_key"] = "invented"
        self.assertIn(
            "unknown journal business effect", validator.financial_invariants(data)
        )

    def test_duplicate_entry_ids_are_rejected(self):
        data = snapshot()
        data["entries"][1]["id"] = 1
        self.assertIn("duplicate entry ID", validator.financial_invariants(data))

    def test_missing_or_diverged_migration_is_rejected(self):
        data = snapshot()
        data["migration"][0]["captured_minor"] = 1
        self.assertIn(
            "migration representation differs", validator.financial_invariants(data)
        )
        data["migration"] = []
        self.assertIn(
            "migration missing or extra objects", validator.financial_invariants(data)
        )

    def test_unpublished_and_orphan_events_are_rejected(self):
        data = snapshot()
        data["events"][0]["published_at"] = None
        data["events"][1]["aggregate_id"] = "absent"
        errors = validator.financial_invariants(data)
        self.assertIn("event not drained", errors)
        self.assertIn("orphan event", errors)

    def test_over_refund_and_unbalanced_journal_are_rejected(self):
        data = snapshot()
        data["payments"][0]["amount_refunded"] = 1001
        data["entries"][0]["debit"] = 999
        errors = validator.financial_invariants(data)
        self.assertIn("money bounds violated", errors)
        self.assertIn("unposted/unbalanced journal", errors)

    def test_percentile_interpolates_raw_samples(self):
        self.assertAlmostEqual(validator.percentile([0, 10, 20], 0.95), 19)


if __name__ == "__main__":
    unittest.main()
