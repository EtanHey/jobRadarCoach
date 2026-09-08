#!/usr/bin/env python3
"""Fail-closed, read-only verifier for Job Radar voice-agent receipts."""

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED_TABLES = ("posting_status", "profile", "active_mic")
V2_ADDITIONAL_FIELDS = {"mode", "worker_load_threshold", "host_load_at_startup"}


class NotReady(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def fail(code: str, detail: str) -> "None":
    raise NotReady(code, detail)


def process_start_time(pid: int) -> dict[str, str]:
    proc_stat = Path(f"/proc/{pid}/stat")
    boot_id = Path("/proc/sys/kernel/random/boot_id")
    if proc_stat.is_file() and boot_id.is_file():
        fields = proc_stat.read_text().split()
        return {
            "source": "linux_boot_id_and_start_ticks",
            "value": f"{boot_id.read_text().strip()}:{fields[21]}",
        }
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail("process_not_live", f"cannot read process {pid}: {type(exc).__name__}")
    value = " ".join(result.stdout.split())
    if not value:
        fail("process_not_live", f"process {pid} has no start identity")
    return {"source": "ps_lstart", "value": value}


def host_load_per_cpu() -> float:
    # os.getloadavg() raises OSError where load average is unobtainable. Without this,
    # main() emits a traceback instead of the contracted compact NOT_READY JSON.
    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError) as exc:
        fail("load_unavailable", f"host load sampling failed: {exc}")
    return load / (os.cpu_count() or 1)


def require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        fail("invalid_receipt", f"{path} must be an object")
    return value


def require_keys(
    value: dict[str, object],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    path: str,
) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing or extra:
        fail(
            "invalid_receipt",
            f"{path} fields differ from schema (missing={sorted(missing)}, extra={sorted(extra)})",
        )


def validate_v1_receipt(payload: object) -> dict[str, object]:
    receipt = require_object(payload, "receipt")
    require_keys(
        receipt,
        required={
            "schema_version",
            "status",
            "process",
            "startup",
            "registration",
            "database",
            "reason",
            "written_at",
        },
        optional={"error_type"},
        path="receipt",
    )
    if receipt.get("schema_version") != 1:
        fail("unsupported_schema", "schema_version must be 1")
    if receipt.get("status") != "ready":
        fail("receipt_not_ready", f"status is {receipt.get('status')!r}")
    if receipt.get("reason") is not None or "error_type" in receipt:
        fail("invalid_receipt", "a ready receipt cannot carry failure fields")
    written_at = receipt.get("written_at")
    if not isinstance(written_at, str):
        fail("invalid_receipt", "written_at must be a date-time string")
    try:
        datetime.fromisoformat(written_at.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_receipt", "written_at must be an RFC 3339 date-time")

    process = require_object(receipt.get("process"), "process")
    require_keys(process, required={"pid", "start_time"}, path="process")
    pid = process.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        fail("invalid_receipt", "process.pid must be a positive integer")
    expected_start = require_object(process.get("start_time"), "process.start_time")
    require_keys(
        expected_start,
        required={"source", "value"},
        path="process.start_time",
    )
    if process_start_time(pid) != expected_start:
        fail("stale_process_identity", "PID start identity does not match receipt")

    startup = require_object(receipt.get("startup"), "startup")
    require_keys(
        startup,
        required={
            "voice_qa_mode",
            "command_mode",
            "room_mode",
            "livekit_agent_name",
        },
        path="startup",
    )
    if startup.get("voice_qa_mode") != "1":
        fail("qa_mode_missing", "startup.voice_qa_mode must equal '1'")
    if (
        startup.get("command_mode") not in {"dev", "start"}
        or startup.get("room_mode") is not True
    ):
        fail("not_room_mode", "agent did not start in dev/start room mode")
    if startup.get("livekit_agent_name") != "":
        fail("not_automatic_registration", "LIVEKIT_AGENT_NAME is not empty")

    registration = require_object(receipt.get("registration"), "registration")
    require_keys(
        registration,
        required={"server_url", "worker_id", "automatic", "effective_agent_name"},
        path="registration",
    )
    if (
        registration.get("automatic") is not True
        or registration.get("effective_agent_name") != ""
    ):
        fail("not_automatic_registration", "effective registration is named")
    worker_id = registration.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        fail("registration_missing", "registered worker_id is empty")
    server_url = registration.get("server_url")
    if not isinstance(server_url, str):
        fail("server_url_missing", "registration.server_url is missing")
    parsed_url = urlsplit(server_url)
    if (
        parsed_url.scheme not in {"ws", "wss"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        fail(
            "unsafe_server_url",
            "registration.server_url is not a credential-free ws/wss URL",
        )
    expected_url = os.environ.get("LIVEKIT_URL")
    if not expected_url:
        fail(
            "expected_server_missing",
            "LIVEKIT_URL must identify the runner's expected server",
        )
    if server_url != expected_url:
        fail("wrong_server", "receipt server URL differs from LIVEKIT_URL")

    database = require_object(receipt.get("database"), "database")
    require_keys(
        database,
        required={"transaction_read_only", "owner_tables"},
        path="database",
    )
    if database.get("transaction_read_only") is not True:
        fail("database_not_read_only", "transaction_read_only is not true")
    tables = require_object(database.get("owner_tables"), "database.owner_tables")
    if set(tables) != set(REQUIRED_TABLES):
        fail("owner_snapshot_missing", "owner table set is not exact")
    for table_name in REQUIRED_TABLES:
        witness = require_object(tables[table_name], f"owner_tables.{table_name}")
        require_keys(
            witness,
            required={"count", "sha256"},
            path=f"owner_tables.{table_name}",
        )
        count = witness.get("count")
        digest = witness.get("sha256")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            fail("owner_snapshot_invalid", f"{table_name}.count is invalid")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            fail("owner_snapshot_invalid", f"{table_name}.sha256 is invalid")
    return receipt


def validate_availability(receipt: dict[str, object]) -> None:
    threshold = receipt.get("worker_load_threshold")
    startup_load = receipt.get("host_load_at_startup")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or threshold <= 0
    ):
        fail("invalid_receipt", "worker_load_threshold must be a positive number")
    if (
        not isinstance(startup_load, (int, float))
        or isinstance(startup_load, bool)
        or not math.isfinite(startup_load)
        or startup_load < 0
    ):
        fail("invalid_receipt", "host_load_at_startup must be a non-negative number")


def verify_live_load(receipt: dict[str, object]) -> None:
    threshold = receipt.get("worker_load_threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        fail("threshold_unknown", "worker load threshold is unavailable")
    if host_load_per_cpu() >= threshold:
        fail(
            "over_load_threshold",
            "current host load is at or above worker_load_threshold",
        )


def validate_v2_normal_receipt(receipt: dict[str, object]) -> dict[str, object]:
    if receipt.get("status") != "ready":
        fail("receipt_not_ready", f"status is {receipt.get('status')!r}")
    if receipt.get("reason") is not None or "error_type" in receipt:
        fail("invalid_receipt", "a ready receipt cannot carry failure fields")
    written_at = receipt.get("written_at")
    if not isinstance(written_at, str):
        fail("invalid_receipt", "written_at must be a date-time string")
    try:
        datetime.fromisoformat(written_at.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_receipt", "written_at must be an RFC 3339 date-time")

    process = require_object(receipt.get("process"), "process")
    require_keys(process, required={"pid", "start_time"}, path="process")
    pid = process.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        fail("invalid_receipt", "process.pid must be a positive integer")
    expected_start = require_object(process.get("start_time"), "process.start_time")
    require_keys(expected_start, required={"source", "value"}, path="process.start_time")
    if process_start_time(pid) != expected_start:
        fail("stale_process_identity", "PID start identity does not match receipt")

    startup = require_object(receipt.get("startup"), "startup")
    require_keys(
        startup,
        required={
            "voice_qa_mode",
            "command_mode",
            "room_mode",
            "livekit_agent_name",
        },
        path="startup",
    )
    if startup.get("voice_qa_mode") not in {None, "", "0"}:
        fail(
            "normal_mode_missing",
            "startup.voice_qa_mode must be unset, empty, or equal '0'",
        )
    if (
        startup.get("command_mode") not in {"dev", "start"}
        or startup.get("room_mode") is not True
    ):
        fail("not_room_mode", "agent did not start in dev/start room mode")
    if startup.get("livekit_agent_name") != "":
        fail("not_automatic_registration", "LIVEKIT_AGENT_NAME is not empty")

    registration = require_object(receipt.get("registration"), "registration")
    require_keys(
        registration,
        required={"server_url", "worker_id", "automatic", "effective_agent_name"},
        path="registration",
    )
    if (
        registration.get("automatic") is not True
        or registration.get("effective_agent_name") != ""
    ):
        fail("not_automatic_registration", "effective registration is named")
    worker_id = registration.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        fail("registration_missing", "registered worker_id is empty")
    server_url = registration.get("server_url")
    if not isinstance(server_url, str):
        fail("server_url_missing", "registration.server_url is missing")
    parsed_url = urlsplit(server_url)
    if (
        parsed_url.scheme not in {"ws", "wss"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        fail(
            "unsafe_server_url",
            "registration.server_url is not a credential-free ws/wss URL",
        )
    expected_url = os.environ.get("LIVEKIT_URL")
    if not expected_url:
        fail(
            "expected_server_missing",
            "LIVEKIT_URL must identify the runner's expected server",
        )
    if server_url != expected_url:
        fail("wrong_server", "receipt server URL differs from LIVEKIT_URL")
    if receipt.get("database") is not None:
        fail("normal_database_evidence_present", "database must be null in normal mode")
    return receipt


def validate_v2_receipt(
    receipt: dict[str, object], *, require_mode: str
) -> dict[str, object]:
    require_keys(
        receipt,
        required={
            "schema_version",
            "mode",
            "worker_load_threshold",
            "host_load_at_startup",
            "status",
            "process",
            "startup",
            "registration",
            "database",
            "reason",
            "written_at",
        },
        optional={"error_type"},
        path="receipt",
    )
    mode = receipt.get("mode")
    if mode not in {"normal", "qa"}:
        fail("invalid_receipt", "mode must be 'normal' or 'qa'")
    if mode != require_mode:
        fail("wrong_mode", f"receipt mode is {mode!r}, required {require_mode!r}")
    validate_availability(receipt)
    if mode == "normal":
        return validate_v2_normal_receipt(receipt)

    legacy_projection = {
        key: value for key, value in receipt.items() if key not in V2_ADDITIONAL_FIELDS
    }
    legacy_projection["schema_version"] = 1
    validate_v1_receipt(legacy_projection)
    return receipt


def validate_receipt(payload: object, *, require_mode: str) -> dict[str, object]:
    receipt = require_object(payload, "receipt")
    schema_version = receipt.get("schema_version")
    if schema_version == 1:
        if require_mode != "qa":
            fail("wrong_mode", "schema version 1 receipts are QA-only")
        return validate_v1_receipt(receipt)
    if schema_version == 2:
        return validate_v2_receipt(receipt, require_mode=require_mode)
    fail("unsupported_schema", "schema_version must be 1 or 2")


def kubectl_json(arguments: list[str]) -> object:
    command = ["kubectl", *arguments]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return json.loads(result.stdout)
    except FileNotFoundError:
        fail("pool_query_unavailable", "kubectl is unavailable")
    except subprocess.TimeoutExpired:
        fail("pool_query_timeout", "LiveKit registration-pool query timed out")
    except subprocess.CalledProcessError as exc:
        fail("pool_query_failed", f"kubectl exited {exc.returncode}")
    except json.JSONDecodeError:
        fail("pool_query_invalid", "kubectl returned invalid JSON")


def kubectl_logs(namespace: str, pod: str) -> str:
    try:
        result = subprocess.run(
            ["kubectl", "-n", namespace, "logs", pod, "--timestamps"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout
    except FileNotFoundError:
        fail("pool_query_unavailable", "kubectl is unavailable")
    except subprocess.TimeoutExpired:
        fail("pool_query_timeout", "LiveKit registration log query timed out")
    except subprocess.CalledProcessError as exc:
        fail("pool_query_failed", f"kubectl logs exited {exc.returncode}")


def parse_log_record(line: str) -> dict[str, object] | None:
    opening = line.rfind("{")
    if opening < 0:
        return None
    try:
        value = json.loads(line[opening:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def registration_pool() -> dict[str, dict[str, object]]:
    namespace = os.environ.get("LIVEKIT_K8S_NAMESPACE", "job-radar-coach")
    selector = os.environ.get("LIVEKIT_K8S_SELECTOR", "app=livekit")
    pod_list = require_object(
        kubectl_json(["-n", namespace, "get", "pods", "-l", selector, "-o", "json"]),
        "pod list",
    )
    items = pod_list.get("items")
    if not isinstance(items, list):
        fail("pool_query_invalid", "pod list items are missing")
    ready_pods = []
    for item in items:
        pod = require_object(item, "pod")
        metadata = require_object(pod.get("metadata"), "pod.metadata")
        status = require_object(pod.get("status"), "pod.status")
        conditions = status.get("conditions")
        ready = isinstance(conditions, list) and any(
            isinstance(condition, dict)
            and condition.get("type") == "Ready"
            and condition.get("status") == "True"
            for condition in conditions
        )
        if status.get("phase") == "Running" and ready:
            ready_pods.append((metadata, status))
    if len(ready_pods) != 1:
        fail(
            "pool_topology_ambiguous",
            f"expected 1 ready LiveKit pod, found {len(ready_pods)}",
        )

    metadata, pod_status = ready_pods[0]
    pod_name = metadata.get("name")
    pod_started = pod_status.get("startTime")
    if not isinstance(pod_name, str) or not isinstance(pod_started, str):
        fail("pool_query_invalid", "LiveKit pod identity/start time is missing")
    logs = kubectl_logs(namespace, pod_name)
    lines = logs.splitlines()
    if not lines:
        fail("pool_history_incomplete", "LiveKit pod logs are empty")
    try:
        pod_start = datetime.fromisoformat(pod_started.replace("Z", "+00:00"))
        first_log_time = datetime.fromisoformat(
            lines[0].split(maxsplit=1)[0].replace("Z", "+00:00")
        )
    except (ValueError, IndexError):
        fail("pool_history_incomplete", "cannot prove logs begin at pod startup")
    if abs((first_log_time - pod_start).total_seconds()) > 15:
        fail(
            "pool_history_incomplete", "LiveKit logs do not cover current pod lifetime"
        )

    active: dict[str, dict[str, object]] = {}
    for line in lines:
        record = parse_log_record(line)
        if record is None:
            continue
        worker_id = record.get("workerID")
        if not isinstance(worker_id, str) or not worker_id:
            continue
        if "worker registered" in line:
            active[worker_id] = record
        elif "closing worker" in line or "last worker deregistered" in line:
            active.pop(worker_id, None)
    return active


def verify_pool(receipt: dict[str, object]) -> None:
    registration = require_object(receipt["registration"], "registration")
    expected_worker = registration["worker_id"]
    pool = registration_pool()
    if expected_worker not in pool:
        fail(
            "worker_not_registered",
            "receipt worker is not in the current LiveKit registration pool",
        )
    expected_record = pool[expected_worker]
    if (
        expected_record.get("agentName") != ""
        or expected_record.get("jobType") != "JT_ROOM"
    ):
        fail(
            "wrong_dispatch_mode",
            "receipt worker is not registered for automatic room dispatch",
        )
    automatic_room_workers = {
        worker_id: record
        for worker_id, record in pool.items()
        if record.get("agentName") == "" and record.get("jobType") == "JT_ROOM"
    }
    unknown = sorted(set(automatic_room_workers) - {expected_worker})
    if unknown:
        fail(
            "unexpected_automatic_worker",
            f"{len(unknown)} additional automatic room worker(s) are registered",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-mode", required=True, choices=("normal", "qa"))
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    try:
        with args.receipt.open(encoding="utf-8") as handle:
            receipt = validate_receipt(json.load(handle), require_mode=args.require_mode)
        if receipt["schema_version"] == 1:
            fail(
                "threshold_unknown",
                "schema version 1 has no worker_load_threshold",
            )
        verify_live_load(receipt)
        verify_pool(receipt)
    except FileNotFoundError:
        print('{"status":"NOT_READY","reason":"receipt_missing"}')
        print("NOT_READY receipt_missing receipt file does not exist", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print('{"status":"NOT_READY","reason":"invalid_receipt"}')
        print("NOT_READY invalid_receipt receipt is not valid JSON", file=sys.stderr)
        return 1
    except NotReady as exc:
        print(json.dumps({"status": "NOT_READY", "reason": exc.code}, separators=(",", ":")))
        print(f"NOT_READY {exc.code} {exc}", file=sys.stderr)
        return 1

    worker_id = require_object(receipt["registration"], "registration")["worker_id"]
    output = {"status": "READY"}
    if receipt["schema_version"] == 2:
        output["mode"] = receipt["mode"]
    output["worker_id"] = worker_id
    print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
