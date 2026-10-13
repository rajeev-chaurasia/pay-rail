#!/usr/bin/env python3
"""Seal the local producer output; checksums do not authenticate its publisher."""

import hashlib
import json
from pathlib import Path
import sys


directory = Path(sys.argv[1] if len(sys.argv) > 1 else "evidence/concurrency")
manifest_path = directory / "manifest.json"
manifest_path.write_text(
    json.dumps(json.loads(manifest_path.read_text()), indent=2) + "\n", encoding="utf-8"
)
digest = hashlib.sha256()
for path in [
    Path("src/test/java/com/payrail/ConcurrencyEvidenceHarness.java"),
    Path("scripts/validate_concurrency_evidence.py"),
]:
    digest.update(path.read_bytes())
(directory / "producer.sha256").write_text(digest.hexdigest() + "\n", encoding="utf-8")
hashes = {
    name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
    for name in ["raw.csv", "manifest.json", "producer.sha256"]
}
(directory / "checksums.json").write_text(
    json.dumps(hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8"
)
