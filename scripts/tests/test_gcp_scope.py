import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "cloud", Path(__file__).parents[1] / "gcp/cloud.py"
)
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class GcpScopeTest(unittest.TestCase):
    def test_changed_identity_and_foreign_owner_cannot_be_deleted(self):
        resource = {"kind": "instances", "id": "123"}
        cloud.owned(resource, {"id": "123", "labels": {"payrail-run": "run"}}, "run")
        for actual in (
            {"id": "124", "labels": {"payrail-run": "run"}},
            {"id": "123", "labels": {"payrail-run": "other"}},
            {"id": "123", "labels": {}},
        ):
            with self.assertRaises(ValueError):
                cloud.owned(resource, actual, "run")

    def test_network_marker_must_match_exactly(self):
        resource = {"kind": "networks", "id": "123"}
        cloud.owned(
            resource, {"id": "123", "description": "PayRail qualification run"}, "run"
        )
        with self.assertRaises(ValueError):
            cloud.owned(
                resource, {"id": "123", "description": "Existing mediagent"}, "run"
            )


if __name__ == "__main__":
    unittest.main()
