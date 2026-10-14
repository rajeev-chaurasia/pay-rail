import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "faults", Path(__file__).parents[1] / "gcp/validate_faults.py"
)
faults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(faults)


class CloudFaultTest(unittest.TestCase):
    def test_repeated_actions_and_changed_replay_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "faults.bin"
            digest = bytes.fromhex("a" * 64)
            zero = bytes(32)
            first = faults.RECORD.pack(
                0, 0, 3, 1, 200, 200, 1000, 1000000000, 200, digest, digest
            )
            second = faults.RECORD.pack(
                1, 0, 1, 1, 200, 0, 1000, 2000000000, 0, digest, zero
            )
            path.write_bytes(first + second)
            Path(str(path) + ".summary.json").write_text(
                json.dumps(
                    {
                        "attempted_actions": 2,
                        "counted_actions": 2,
                        "class_counts": {"1": 1, "3": 1},
                        "failures": 0,
                        "original_capture_response_losses": 1,
                    }
                )
            )
            Path(str(path) + ".fixtures.json").write_text(
                json.dumps({"fixtures": [{"capture_sha256": "a" * 64}]})
            )
            self.assertTrue(faults.analyze(path)["protocol_gate_passed"])
            for raw in (
                first + first,
                first + second[:-32],
                first
                + faults.RECORD.pack(
                    1, 0, 1, 1, 200, 0, 1000, 2000000000, 0, zero, zero
                ),
            ):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    faults.analyze(path)


if __name__ == "__main__":
    unittest.main()
