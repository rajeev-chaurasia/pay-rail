#!/usr/bin/env python3
"""Explicitly scoped temporary GCP resources with identity-checked cleanup."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "medi-agent-490106"
ACCOUNT = "rajeevchaurasia.tech@gmail.com"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cloud(*args):
    result = subprocess.run(
        [
            "gcloud",
            *args,
            "--project=" + PROJECT,
            "--account=" + ACCOUNT,
            "--format=json",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode:
        sys.stderr.write(result.stderr)
        result.check_returncode()
    return json.loads(result.stdout or "null")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def baseline():
    # Select only identity/status fields, never environment variables or metadata.
    services = cloud("run", "services", "list")
    return {
        "cloud_run": [
            {
                "name": s["metadata"]["name"],
                "uid": s["metadata"].get("uid"),
                "revision": s.get("status", {}).get("latestReadyRevisionName"),
            }
            for s in services
        ],
        "instances": [
            {"name": s["name"], "id": s["id"]}
            for s in cloud("compute", "instances", "list")
        ],
        "disks": [
            {"name": s["name"], "id": s["id"]}
            for s in cloud("compute", "disks", "list")
        ],
    }


def describe(resource):
    args = ["compute", *resource["kind"].split(), "describe", resource["name"]]
    if resource.get("zone"):
        args.append("--zone=" + resource["zone"])
    if resource.get("region"):
        args.append("--region=" + resource["region"])
    return cloud(*args)


def owned(resource, actual, run):
    require(str(actual["id"]) == str(resource["id"]), "Resource identity changed")
    if resource["kind"] in ("instances", "disks"):
        require(
            actual.get("labels", {}).get("payrail-run") == run,
            "Ownership label missing",
        )
    else:
        require(
            actual.get("description") == "PayRail qualification " + run,
            "Ownership description missing",
        )


def provision(path):
    require(
        not path.exists(), "Manifest already exists; never reuse a resource namespace"
    )
    run = (
        "q-"
        + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    prefix = "payrail-qual-" + run
    zone, region = "us-central1-a", "us-central1"
    quotas = {
        q["metric"]: q
        for q in cloud("compute", "regions", "describe", region)["quotas"]
    }
    for metric, requested in (
        ("CPUS", 40),
        ("E2_CPUS", 8),
        ("SSD_TOTAL_GB", 400),
        ("DISKS_TOTAL_GB", 430),
        ("IN_USE_ADDRESSES", 2),
    ):
        q = quotas[metric]
        require(q["limit"] - q["usage"] >= requested, "Insufficient quota: " + metric)
    data = {
        "project": PROJECT,
        "account": ACCOUNT,
        "run": run,
        "prefix": prefix,
        "zone": zone,
        "region": region,
        "approved_spend_usd": 25,
        "maximum_runtime_hours": 6,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
        "baseline": baseline(),
        "resources": [],
        "state": "provisioning",
    }
    save(path, data)
    key = path.parent / "id_ed25519"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    public = key.with_suffix(".pub").read_text().strip()
    ssh_metadata = path.parent / "ssh-public-metadata.txt"
    ssh_metadata.write_text("payrail:" + public + "\n")
    marker = "PayRail qualification " + run
    labels = "application=payrail,purpose=qualification,payrail-run=" + run

    def create(kind, name, *extra, zone=None, region=None):
        resource = {"kind": kind, "name": name}
        if zone:
            resource["zone"] = zone
            extra += ("--zone=" + zone,)
        if region:
            resource["region"] = region
            extra += ("--region=" + region,)
        # Record attempted names before mutation so interrupted creation is recoverable.
        data["resources"].append(resource)
        save(path, data)
        cloud("compute", kind, "create", name, *extra)
        actual = describe(resource)
        resource["id"] = actual["id"]
        save(path, data)
        return actual

    create("networks", prefix, "--subnet-mode=custom", "--description=" + marker)
    # subnet commands use a nested collection, handled explicitly below.
    subnet = {"kind": "networks subnets", "name": prefix, "region": region}
    data["resources"].append(subnet)
    save(path, data)
    cloud(
        "compute",
        "networks",
        "subnets",
        "create",
        prefix,
        "--network=" + prefix,
        "--range=10.240.0.0/24",
        "--region=" + region,
        "--description=" + marker,
    )
    subnet["id"] = cloud(
        "compute", "networks", "subnets", "describe", prefix, "--region=" + region
    )["id"]
    save(path, data)
    create(
        "firewall-rules",
        prefix + "-iap",
        "--network=" + prefix,
        "--allow=tcp:22",
        "--source-ranges=35.235.240.0/20",
        "--target-tags=" + prefix,
        "--description=" + marker,
    )
    create(
        "firewall-rules",
        prefix + "-load",
        "--network=" + prefix,
        "--allow=tcp:18080",
        "--source-ranges=10.240.0.20/32",
        "--target-tags=" + prefix + "-server",
        "--description=" + marker,
    )
    for role, machine, size, disk_type, address in (
        ("server", "n1-standard-32", 400, "pd-ssd", "10.240.0.10"),
        ("generator", "e2-standard-8", 30, "pd-balanced", "10.240.0.20"),
    ):
        name = prefix + "-" + role
        create(
            "instances",
            name,
            "--machine-type=" + machine,
            "--subnet=" + prefix,
            "--private-network-ip=" + address,
            "--no-service-account",
            "--no-scopes",
            "--image=ubuntu-2404-noble-amd64-v20261009",
            "--image-project=ubuntu-os-cloud",
            "--boot-disk-size=" + str(size),
            "--boot-disk-type=" + disk_type,
            "--boot-disk-auto-delete",
            "--labels=" + labels,
            "--tags=" + prefix + "," + prefix + "-" + role,
            "--termination-time=" + data["expires_at"],
            "--instance-termination-action=DELETE",
            "--no-restart-on-failure",
            "--metadata=block-project-ssh-keys=true,enable-oslogin=false",
            "--metadata-from-file=ssh-keys="
            + str(ssh_metadata)
            + ",startup-script="
            + str(ROOT / "deploy/gcp/bootstrap.sh"),
            zone=zone,
        )
        disk = {"kind": "disks", "name": name, "zone": zone}
        cloud(
            "compute",
            "disks",
            "add-labels",
            name,
            "--zone=" + zone,
            "--labels=" + labels,
        )
        disk["id"] = describe(disk)["id"]
        data["resources"].append(disk)
        save(path, data)
    data["state"] = "provisioned"
    save(path, data)
    print("Provisioned isolated resources; manifest: " + str(path))


def cleanup(path):
    data = json.loads(path.read_text())
    require(
        data["project"] == PROJECT and data["prefix"] == "payrail-qual-" + data["run"],
        "Unexpected cleanup scope",
    )
    # Instances first so auto-delete boot disks cannot remain attached.
    order = {
        "instances": 0,
        "disks": 1,
        "firewall-rules": 2,
        "networks subnets": 3,
        "networks": 4,
    }
    for resource in sorted(data["resources"], key=lambda r: order[r["kind"]]):
        require(
            resource["name"].startswith(data["prefix"]),
            "Resource is outside run namespace",
        )
        args = ["compute", *resource["kind"].split(), "describe", resource["name"]]
        scope = ["--zone=" + resource["zone"]] if resource.get("zone") else []
        if resource.get("region"):
            scope = ["--region=" + resource["region"]]
        try:
            actual = cloud(*args, *scope)
        except subprocess.CalledProcessError as error:
            require(
                "not found" in error.stderr.lower()
                or "was not found" in error.stderr.lower(),
                "Cannot verify resource absence",
            )
            continue
        if "id" not in resource:
            resource["id"] = actual["id"]
        owned(resource, actual, data["run"])
        if resource["kind"] == "disks":
            require(not actual.get("users"), "Refuse to delete an attached disk")
        cloud("compute", *resource["kind"].split(), "delete", resource["name"], *scope)
    after = baseline()
    require(
        after == data["baseline"],
        "Existing resource identities changed; inspect before declaring cleanup complete",
    )
    data["state"] = "cleaned"
    data["baseline_after"] = after
    data["cleaned_at"] = datetime.now(timezone.utc).isoformat()
    save(path, data)
    print("Run-owned resources removed; existing resource identities match baseline")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("provision", "cleanup"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    require(
        "artifacts" in args.manifest.parts,
        "Keep manifests and keys in ignored artifacts",
    )
    if args.action == "provision":
        provision(args.manifest)
    else:
        cleanup(args.manifest)


if __name__ == "__main__":
    main()
