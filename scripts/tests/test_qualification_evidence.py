import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "qualification", Path(__file__).parents[1] / "validate_qualification_evidence.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RedeliveryEvidenceTest(unittest.TestCase):
    def fixture(self):
        return {
            "schema": "payrail-provider-redelivery-v1",
            "configured_redeliveries": 8,
            "workers": [
                {
                    "worker": n,
                    "start_nanos": n + 1,
                    "end_nanos": 20 + n,
                    "completed_calls": 1,
                }
                for n in range(8)
            ],
            "snapshot": {
                "journals": 1,
                "entries": 2,
                "delta": 0,
                "inbox_records": 1,
                "provider_operations": 1,
            },
        }

    def test_accepts_matching_concurrent_observations(self):
        module.validate_redelivery(self.fixture())

    def test_rejects_duplicate_effect_wrong_count_and_serialized_workers(self):
        for kind in ["effect", "count", "workers"]:
            report = copy.deepcopy(self.fixture())
            if kind == "effect":
                report["snapshot"]["journals"] = 2
            elif kind == "count":
                report["workers"][0]["completed_calls"] = 2
            else:
                report["workers"][0]["end_nanos"] = 2
            with self.assertRaises(ValueError):
                module.validate_redelivery(report)
