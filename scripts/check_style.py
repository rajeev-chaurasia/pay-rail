#!/usr/bin/env python3
"""Check repository prose without exposing file contents in diagnostics."""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "em dash": re.compile("\u2014"),
    "en dash": re.compile("\u2013"),
}
SELF = "scripts/check_style.py"


def forbidden_path(path):
    name = Path(path).name
    return (
        (name == ".env" or name.startswith(".env.")) and name != ".env.example"
    ) or name.endswith((".pem", ".key"))


def inspect(root, paths):
    failures = []
    for name in sorted(set(paths)):
        if forbidden_path(name):
            failures.append(f"{name}: forbidden secret-bearing file")
            continue
        path = root / name
        if name == SELF or not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"{name}: invalid UTF-8")
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    failures.append(f"{name}:{number}: {label}")
        if content and not content.endswith("\n"):
            failures.append(f"{name}: missing final newline")
        if "\r" in content:
            failures.append(f"{name}: non-LF line endings")
    return failures


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        samples = {
            "clean.md": "Plain prose.\n",
            "bad.md": "Invalid punctuation \u2014 \u2013\n",
            "AGENTS.md": "Read this contributor contract.\n",
            ".env": "not a real credential\n",
        }
        for name, content in samples.items():
            (root / name).write_text(content, encoding="utf-8")
        failures = inspect(root, samples)
        assert len(failures) == 3, failures
        assert not any(item.startswith(("clean.md:", "AGENTS.md:")) for item in failures)
    print("Style guard negative controls passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, check=True, capture_output=True,
    )
    paths = result.stdout.decode("utf-8").split("\x00")
    failures = inspect(ROOT, [path for path in paths if path])
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Repository style passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
