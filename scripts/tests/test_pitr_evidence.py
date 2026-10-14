import copy
import importlib.util
import json
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "pitr", Path(__file__).parents[1] / "validate_pitr_evidence.py"
)
pitr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pitr)


class PitrEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.good = json.loads(
            (
                Path(__file__).parents[2] / "evidence/flows/postgres-pitr.json"
            ).read_text()
        )

    def test_table_mismatch_and_missing_inventory_are_rejected(self):
        pitr.validate(self.good)
        changed = copy.deepcopy(self.good)
        changed["table_sha256_restored"]["ledger_entries"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "differ"):
            pitr.validate(changed)
        del changed["table_sha256_restored"]["refunds"]
        with self.assertRaisesRegex(ValueError, "inventory"):
            pitr.validate(changed)

    def test_bad_response_and_missing_fault_are_rejected(self):
        for edit in (
            lambda d: d["replays"][0].update(replayed_sha256="0" * 64),
            lambda d: d.update(missing_wal_exit_code=0),
            lambda d: d.update(missing_wal_exit_code=True),
            lambda d: d.update(restored_delivery_fenced=False),
            lambda d: d.update(restore_seconds=float("nan")),
            lambda d: d["journals_after_write"][0]["entries"][0].update(
                debit=1, credit=0
            ),
        ):
            changed = copy.deepcopy(self.good)
            edit(changed)
            with self.assertRaises(ValueError):
                pitr.validate(changed)


if __name__ == "__main__":
    unittest.main()
