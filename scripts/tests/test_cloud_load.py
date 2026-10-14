import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "load", Path(__file__).parents[1] / "gcp/validate_load.py"
)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


class CloudLoadTest(unittest.TestCase):
    def test_missing_duplicate_and_wrong_status_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.bin"
            Path(str(path) + ".summary.json").write_text(
                json.dumps(
                    {
                        "offered": 2,
                        "offered_rate": 1,
                        "duration_seconds": 2,
                        "accepted": 2,
                        "dropped": 0,
                        "unexpected": 0,
                    }
                )
            )
            good = load.RECORD.pack(0, 0, 1000, 201, 1) + load.RECORD.pack(
                1, 1000000, 1000, 201, 1
            )
            path.write_bytes(good)
            self.assertTrue(load.analyze(path)["client_budget_passed"])
            for bad in (
                good[:24],
                good[:24] * 2,
                good[:24] + load.RECORD.pack(1, 1000000, 1000, 429, 1),
            ):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    load.analyze(path)

    def test_arrival_delay_is_included_in_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.bin"
            path.write_bytes(load.RECORD.pack(0, 3000000, 1000, 201, 1))
            Path(str(path) + ".summary.json").write_text(
                json.dumps(
                    {
                        "offered": 1,
                        "offered_rate": 1,
                        "duration_seconds": 1,
                        "accepted": 1,
                        "dropped": 0,
                        "unexpected": 0,
                    }
                )
            )
            self.assertEqual(load.analyze(path)["p99_ms"], 3001)
            self.assertFalse(load.analyze(path)["client_budget_passed"])
