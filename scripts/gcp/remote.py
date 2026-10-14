#!/usr/bin/env python3
"""IAP SSH/SCP without modifying shared project SSH metadata."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess

from cloud import ACCOUNT, PROJECT, describe, owned, require


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("exec", "put", "get"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("role", choices=("server", "generator"))
    parser.add_argument("arguments", nargs="+")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    require(data["project"] == PROJECT, "Unexpected project")
    resource = next(
        r
        for r in data["resources"]
        if r["kind"] == "instances" and r["name"] == data["prefix"] + "-" + args.role
    )
    owned(resource, describe(resource), data["run"])
    proxy = shlex.join(
        [
            "gcloud",
            "compute",
            "start-iap-tunnel",
            "%h",
            "%p",
            "--listen-on-stdin",
            "--project=" + PROJECT,
            "--account=" + ACCOUNT,
            "--zone=" + data["zone"],
            "--verbosity=warning",
        ]
    )
    options = [
        "-i",
        str(args.manifest.parent / "id_ed25519"),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=" + str(args.manifest.parent / "known_hosts"),
        "-o",
        "ProxyCommand=" + proxy,
        "-o",
        "ConnectTimeout=30",
    ]
    target = "payrail@" + resource["name"]
    if args.action == "exec":
        require(len(args.arguments) == 1, "Pass one complete remote command")
        command = ["ssh", *options, target, args.arguments[0]]
    else:
        require(len(args.arguments) == 2, "Transfer requires source and destination")
        source, destination = args.arguments
        if args.action == "put":
            destination = target + ":" + destination
        else:
            source = target + ":" + source
        command = ["scp", *options, source, destination]
    raise SystemExit(subprocess.run(command).returncode)


if __name__ == "__main__":
    main()
