import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/gcp"))
spec = importlib.util.spec_from_file_location("campaign", ROOT / "scripts/gcp/validate_campaign.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
EVIDENCE = ROOT / "evidence/gcp/q-20261014092401-2304be"


class CloudCampaignTest(unittest.TestCase):
    def test_recovered_balance_and_observed_boundaries_are_recomputed(self):
        original = json.loads((EVIDENCE / "crash-drill.json").read_text())
        campaign.recovery_invariants(original)
        for mutation in ("money", "boundary", "duplicate"):
            bad = copy.deepcopy(original)
            if mutation == "money":
                bad["rounds"][0]["inspection"]["journals"][0]["entries"][0]["debit"] += 1
            elif mutation == "boundary":
                bad["actions"][0]["after_running"] = True
            else:
                bad["rounds"][1] = bad["rounds"][0]
            with self.assertRaises(ValueError):
                campaign.recovery_invariants(bad)

    def test_full_reconciliation_range_overlap_and_missed_arrivals_cannot_be_hidden(self):
        m = json.loads((EVIDENCE / "migration/migration-100m.json").read_text())
        p = json.loads((EVIDENCE / "migration/parallel-backfill.json").read_text())
        m["foreground"] = {"attempted": 1, "accepted": 1, "errors": 0, "missed_arrivals": 2}
        raw = '{"ordinal":0,"status":201}\n{"ordinal":1,"missed":2}\n'
        campaign.migration_invariants(m, p, raw)
        for mutation in ("mismatch", "overlap", "missed"):
            bad, ranges = copy.deepcopy(m), copy.deepcopy(p)
            if mutation == "mismatch":
                bad["gate"]["mismatched"] = 1
            elif mutation == "overlap":
                ranges["ranges"][1]["first"] -= 1
            else:
                bad["foreground"]["missed_arrivals"] = 0
            with self.assertRaises(ValueError):
                campaign.migration_invariants(bad, ranges, raw)


if __name__ == "__main__":
    unittest.main()
