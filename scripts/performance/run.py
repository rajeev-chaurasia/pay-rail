#!/usr/bin/env python3
"""Run bounded local k6 studies against a synthetic tenant on an isolated app."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
HOST_ROOT = Path(os.environ.get("PAYRAIL_HOST_WORKSPACE", ROOT))
K6_IMAGE = "grafana/k6:1.3.0"
PROFILES = [
    ("smoke", 10, 15),
    ("sustained-a", 100, 60),
    ("sustained-b", 100, 60),
    ("mixed", 10, 60),
    ("stress", 200, 62),
    ("baseline-a", 25, 60),
    ("baseline-b", 25, 60),
    ("mixed-baseline", 2, 60),
    ("target-probe", 25000, 5),
]


def command(args, data=None, check=True):
    return subprocess.run(args, input=data, text=True, capture_output=True, check=check)


def sql(statement, tenant=None):
    args = [
        "docker",
        "exec",
        "-i",
        "payrail-postgres-1",
        "psql",
        "-X",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "payrail",
        "-d",
        "payrail",
    ]
    if tenant:
        args += ["-v", f"tenant={tenant}"]
    return command(args, statement).stdout.strip()


def request(url, key, options=None):
    options = options or {}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(options.get("headers", {}))
    body = options.get("body")
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method=options.get("method", "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_ready(url):
    for _ in range(60):
        try:
            if request(url + "/actuator/health", "")[0] == 200:
                return
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.RemoteDisconnected,
        ):
            pass
        time.sleep(1)
    raise RuntimeError("Performance app did not become ready")


def environment(names):
    containers = []
    for name in names:
        item = json.loads(command(["docker", "inspect", name]).stdout)[0]
        containers.append(
            {
                "name": name,
                "image_id": item["Image"],
                "memory_limit_bytes": item["HostConfig"]["Memory"],
                "nano_cpus": item["HostConfig"]["NanoCpus"],
            }
        )
    info = json.loads(command(["docker", "info", "--format", "{{json .}}"]).stdout)
    sources = [
        ROOT / "pom.xml",
        ROOT / "scripts/load.js",
        ROOT / "scripts/performance/run.py",
        ROOT / "scripts/performance/snapshot.sql",
    ]
    sources += [ROOT / "Dockerfile", ROOT / "Dockerfile.verify"]
    sources += sorted((ROOT / "src/main/resources").glob("application*.yml"))
    sources += sorted((ROOT / "src/main/resources/db/migration").glob("*.conf"))
    sources += sorted((ROOT / "src/main/java").rglob("*.java")) + sorted(
        (ROOT / "src/main/resources/db/migration").glob("*.sql")
    )
    return {
        "host": platform.platform(),
        "machine": platform.machine(),
        "docker_cpus": info["NCPU"],
        "docker_memory_bytes": info["MemTotal"],
        "containers": containers,
        "k6": command(["docker", "run", "--rm", K6_IMAGE, "version"]).stdout.strip(),
        "k6_image": json.loads(
            command(["docker", "image", "inspect", K6_IMAGE]).stdout
        )[0]["RepoDigests"],
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        "git_revision": command(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "working_tree_dirty": bool(command(["git", "status", "--porcelain"]).stdout),
        "topology": "Two app instances share existing PostgreSQL/Kafka. One existing outbox dispatcher; benchmark app has dedicated Redis. Load generator shares Docker host.",
    }


def fixture(run_id):
    tenant = "tenant_perf_" + run_id.replace("-", "_")
    api_key = "pr_test_performance_" + uuid.uuid4().hex
    digest = hashlib.sha256(
        ("local-development-pepper-change-me:" + api_key).encode()
    ).hexdigest()
    sql(
        f"insert into tenants(id,name) values ('{tenant}','Synthetic performance tenant'); insert into api_keys(tenant_id,key_hash,label) values ('{tenant}','{digest}','performance fixture');"
    )
    return tenant, api_key


def resource_sampler(names, output, stop):
    with output.open("w") as handle:
        while not stop.is_set():
            result = command(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
                check=False,
            )
            for line in result.stdout.splitlines():
                handle.write(
                    json.dumps(
                        {
                            "time": datetime.now(timezone.utc).isoformat(),
                            "stats": json.loads(line),
                        }
                    )
                    + "\n"
                )
            handle.flush()
            stop.wait(5)


def migrate(url, output, stop):
    observations = []
    while not stop.is_set():
        try:
            status, data = request(
                url + "/v1/admin/migrations/payment-v2/backfill?batchSize=500",
                "",
                {"method": "POST", "headers": {"X-Admin-Token": "local-admin-token"}},
            )
            observations.append(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "response": data,
                }
            )
        except Exception as error:
            observations.append({"error": type(error).__name__})
        stop.wait(2)
    output.write_text(json.dumps(observations, indent=2) + "\n")


def drain(tenant, directory):
    observations = []
    deadline = time.monotonic() + 300
    while True:
        counts = json.loads(
            sql(
                "select json_build_object('pending_events',(select count(*) from outbox_events where tenant_id=:'tenant' and published_at is null),'processing',(select count(*) from payment_intents where tenant_id=:'tenant' and status='processing'));",
                tenant,
            )
        )
        observations.append({"time": datetime.now(timezone.utc).isoformat(), **counts})
        if not counts["pending_events"] and not counts["processing"]:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
    directory.joinpath("drain.json").write_text(
        json.dumps(observations, indent=2) + "\n"
    )
    snapshot = json.loads(
        sql((ROOT / "scripts/performance/snapshot.sql").read_text(), tenant)
    )
    with gzip.open(directory / "snapshot.json.gz", "wt") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n")


def seal(directory):
    summary = directory / "summary.json"
    if summary.exists():
        summary.write_text(summary.read_text().rstrip("\n") + "\n")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name not in {"checksums.json", "report.json"}
    }
    directory.joinpath("checksums.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n"
    )


def run_profile(config, profile):
    label, rate, seconds = profile
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-"
        + label
        + "-"
        + uuid.uuid4().hex[:6]
    )
    directory = config["output"] / run_id
    directory.mkdir(parents=True)
    tenant, api_key = fixture(run_id)
    manifest = {
        "schema": "payrail-performance-v1",
        "run_id": run_id,
        "tenant": tenant,
        "profile": label,
        "rate": rate,
        "duration_seconds": seconds,
        "expected_iterations": 28900 if label == "stress" else rate * seconds,
        "limits": {"p95_ms": 1000, "p99_ms": 2000, "unexpected": 0, "dropped": 0},
        "quota_requests_per_minute": 1000000,
        "jvm_heap": "128m..512m",
        "db_pool_size": 20,
        "shadow_read_percent": 100,
        "v2_read_percent": 100,
        "migration_overlap": label in {"mixed", "mixed-baseline"},
        "environment": config["environment"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    directory.joinpath("manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    stop = threading.Event()
    generator = "payrail-k6-" + run_id.lower()
    sampler = threading.Thread(
        target=resource_sampler,
        args=(config["containers"] + [generator], directory / "resources.jsonl", stop),
    )
    sampler.start()
    migration = (
        threading.Thread(
            target=migrate, args=(config["url"], directory / "migration.json", stop)
        )
        if label in {"mixed", "mixed-baseline"}
        else None
    )
    if migration:
        migration.start()
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        generator,
        "--network",
        "payrail_default",
        "--user",
        "0:0",
        "-v",
        f"{HOST_ROOT}/scripts:/scripts:ro",
        "-v",
        f"{HOST_ROOT / directory.resolve().relative_to(ROOT)}:/results",
        "-e",
        f"PAYRAIL_URL=http://{config['app']}:8080",
        "-e",
        f"PAYRAIL_API_KEY={api_key}",
        "-e",
        f"PAYRAIL_RUN_ID={run_id}",
        "-e",
        f"PAYRAIL_PROFILE={'mixed' if label in {'mixed', 'mixed-baseline'} else label if label in {'stress', 'target-probe'} else 'sustained'}",
        "-e",
        f"PAYRAIL_RATE={rate}",
        "-e",
        f"PAYRAIL_DURATION={seconds}s",
        K6_IMAGE,
        "run",
        "--out",
        "json=/results/raw.json.gz",
        "/scripts/load.js",
    ]
    result = command(args, check=False)
    stop.set()
    sampler.join()
    if migration:
        migration.join()
    directory.joinpath("k6.log").write_text(result.stdout + "\n" + result.stderr)
    manifest.update(
        {
            "exit_code": result.returncode,
            "load_finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    directory.joinpath("manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    drain(tenant, directory)
    sql("update api_keys set enabled=false where tenant_id=:'tenant';", tenant)
    seal(directory)
    print(f"{label}: k6 exit {result.returncode}; {directory}", flush=True)
    return directory


def failure_checks(config):
    tenant, api_key = fixture("flow_" + uuid.uuid4().hex[:8])
    minute = int(time.time() // 60)
    for window in [minute, minute + 1]:
        command(
            [
                "docker",
                "exec",
                config["redis"],
                "redis-cli",
                "SET",
                f"rate:{tenant}:{window}",
                "1000000",
                "EX",
                "65",
            ]
        )
    quota = request(config["url"] + "/v1/payment_intents", api_key)
    assert quota[0] == 429, quota
    for window in [minute, minute + 1]:
        command(
            [
                "docker",
                "exec",
                config["redis"],
                "redis-cli",
                "DEL",
                f"rate:{tenant}:{window}",
            ]
        )
    command(["docker", "stop", config["redis"]])
    try:
        outage = request(config["url"] + "/v1/payment_intents", api_key)
        assert outage[0] == 503, outage
    finally:
        command(["docker", "start", config["redis"]])
    recovered = None
    for _ in range(20):
        recovered = request(config["url"] + "/v1/payment_intents", api_key)
        if recovered[0] == 200:
            break
        time.sleep(1)
    assert recovered[0] == 200, recovered
    sql("update api_keys set enabled=false where tenant_id=:'tenant';", tenant)
    config["output"].mkdir(parents=True, exist_ok=True)
    config["output"].joinpath("admission-failure-checks.json").write_text(
        json.dumps(
            {
                "quota": {"status": quota[0], "body": quota[1]},
                "redis_outage": {"status": outage[0], "body": outage[1]},
                "recovery_status": recovered[0],
            },
            indent=2,
        )
        + "\n"
    )
    print("Real Redis HTTP checks: quota429, outage503, recovery200", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/performance")
    parser.add_argument(
        "--profiles", default="smoke,sustained-a,sustained-b,mixed,stress"
    )
    parser.add_argument(
        "--rate",
        type=int,
        help="Override rate for a single selected non-stress profile",
    )
    parser.add_argument(
        "--duration",
        type=int,
        help="Override duration in seconds for a single selected non-stress profile",
    )
    args = parser.parse_args()
    if (args.rate is not None or args.duration is not None) and (
        "," in args.profiles or args.profiles == "stress"
    ):
        parser.error("Rate/duration overrides require one non-stress profile")
    if args.rate is not None and not 1 <= args.rate <= 1000:
        parser.error(
            "Local rate must be 1..1000; qualification requires a separately sized harness"
        )
    if args.duration is not None and not 1 <= args.duration <= 600:
        parser.error("Local duration must be 1..600 seconds")
    known = {p[0] for p in PROFILES}
    if not set(args.profiles.split(",")) <= known:
        parser.error("Unknown profile")
    suffix = uuid.uuid4().hex[:8]
    app = f"payrail-perf-app-{suffix}"
    redis = f"payrail-perf-redis-{suffix}"
    config = {
        "app": app,
        "redis": redis,
        "url": f"http://{app}:8080"
        if os.environ.get("PAYRAIL_CONTAINERIZED") == "true"
        else "http://localhost:18081",
        "output": args.output,
        "containers": [
            "payrail-postgres-1",
            "payrail-kafka-1",
            "payrail-app-1",
            app,
            redis,
        ],
    }
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                redis,
                "--label",
                "payrail.performance=local",
                "--network",
                "payrail_default",
                "redis:7.4.1-alpine",
            ]
        )
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                app,
                "--label",
                "payrail.performance=local",
                "--network",
                "payrail_default",
                "-p",
                "127.0.0.1:18081:8080",
                "-e",
                "DATABASE_URL=jdbc:postgresql://postgres:5432/payrail",
                "-e",
                f"REDIS_HOST={redis}",
                "-e",
                "KAFKA_BOOTSTRAP_SERVERS=kafka:29092",
                "-e",
                "RATE_LIMIT_RPM=1000000",
                "-e",
                "OUTBOX_ENABLED=false",
                "-e",
                "MIGRATION_SHADOW_READ_PERCENT=100",
                "-e",
                "MIGRATION_V2_READ_PERCENT=100",
                "-e",
                "JAVA_TOOL_OPTIONS=-Xms128m -Xmx512m",
                "payrail-app",
            ]
        )
        wait_ready(config["url"])
        config["environment"] = environment(config["containers"])
        failure_checks(config)
        for profile in PROFILES:
            if profile[0] in args.profiles.split(","):
                if args.rate is not None or args.duration is not None:
                    profile = (
                        profile[0],
                        args.rate or profile[1],
                        args.duration or profile[2],
                    )
                run_profile(config, profile)
    finally:
        for name in [app, redis]:
            command(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    main()
