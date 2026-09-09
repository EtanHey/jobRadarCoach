#!/usr/bin/env python3
"""Run one correlated scraper, extractor, and classifier Kubernetes batch."""
from __future__ import annotations
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid4
NAMESPACE = "job-radar-coach"
STAGE_DEADLINE = 900
JOB_TTL_SECONDS = 3600
RUN_DEADLINE = 2800
READ_ATTEMPTS = 3
READ_RETRY_DELAY_SECONDS = 0.25
REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
class CoordinatorError(RuntimeError):
    pass

@dataclass(frozen=True)
class BatchConfig:
    limit: int = 1
    timeout_seconds: float = 120
    scraper_image: str | None = None
    extractor_image: str | None = None
    classifier_image: str | None = None
    extractor_provider: str | None = None
    classifier_provider: str | None = None
    all_observed: bool = False
    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 30:
            raise ValueError("batch limit must be between 1 and 30")
        if type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout must be between 0 and 120 seconds")
        if any(value not in (None, "ollama", "codex") for value in
               (self.extractor_provider, self.classifier_provider)):
            raise ValueError("provider must be ollama or codex")
        if any(value is not None and not value.strip() for value in
               (self.scraper_image, self.extractor_image, self.classifier_image)):
            raise ValueError("image overrides must be nonblank")
        if type(self.all_observed) is not bool:
            raise ValueError("all_observed must be a boolean")

def _run(command: Sequence[str], *, input_text: str | None, timeout: float) -> str:
    try:
        result = subprocess.run(
            list(command), input=input_text, text=True, capture_output=True,
            timeout=timeout, check=False, shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CoordinatorError("KubectlTimeout") from error
    except OSError as error:
        raise CoordinatorError("KubectlUnavailable") from error
    if result.returncode:
        raise CoordinatorError("KubectlFailed")
    return result.stdout

class Kubectl:
    def __init__(self, runner: Callable[..., str] = _run) -> None:
        self.runner = runner
        self.deadline = time.monotonic() + RUN_DEADLINE
    def text(self, args: Sequence[str], input_text: str | None = None) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CoordinatorError("RunDeadlineExceeded")
        return self.runner(
            ["kubectl", *args], input_text=input_text,
            timeout=max(0.01, min(30, remaining)),
        )
    def json(self, args: Sequence[str], input_text: str | None = None) -> dict[str, Any]:
        try:
            value = json.loads(self.text(args, input_text))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise CoordinatorError("InvalidKubectlJSON") from error
        if not isinstance(value, dict):
            raise CoordinatorError("InvalidKubectlJSON")
        return value

    def _read(self, operation: Callable[[], Any]) -> Any:
        for attempt in range(READ_ATTEMPTS):
            try:
                return operation()
            except CoordinatorError as error:
                if str(error) != "KubectlTimeout" or attempt + 1 == READ_ATTEMPTS:
                    raise
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise CoordinatorError("RunDeadlineExceeded") from error
                time.sleep(min(READ_RETRY_DELAY_SECONDS, remaining))
        raise AssertionError("unreachable")

    def read_text(self, args: Sequence[str]) -> str:
        return self._read(lambda: self.text(args))

    def read_json(self, args: Sequence[str]) -> dict[str, Any]:
        return self._read(lambda: self.json(args))

def _container(job: dict[str, Any], stage: str) -> dict[str, Any]:
    try:
        containers = job["spec"]["template"]["spec"]["containers"]
    except (KeyError, TypeError) as error:
        raise CoordinatorError("InvalidJobTemplate") from error
    matches = [item for item in containers if isinstance(item, dict) and item.get("name") == stage]
    if len(matches) != 1:
        raise CoordinatorError("InvalidJobTemplate")
    return matches[0]

def _prepare_job(
    source: dict[str, Any], stage: str, run_id: str, image: str | None,
    args: list[str] | None = None, provider: str | None = None,
    chunk: int | None = None,
) -> dict[str, Any]:
    job = copy.deepcopy(source)
    if job.get("kind") != "Job":
        raise CoordinatorError("InvalidJobTemplate")
    labels = {"job-radar-coach/run-id": run_id, "job-radar-coach/stage": stage}
    if chunk is not None:
        labels["job-radar-coach/chunk"] = str(chunk)
    suffix = "" if chunk is None else f"-{chunk:03d}"
    job["apiVersion"] = "batch/v1"
    job["metadata"] = {
        "name": f"{stage}-{run_id}{suffix}", "namespace": NAMESPACE, "labels": labels,
    }
    spec = job.setdefault("spec", {})
    spec.update(
        activeDeadlineSeconds=STAGE_DEADLINE,
        backoffLimit=0,
        ttlSecondsAfterFinished=JOB_TTL_SECONDS,
    )
    template = spec.setdefault("template", {})
    template["metadata"] = {"labels": labels}
    template.setdefault("spec", {})["restartPolicy"] = "Never"
    container = _container(job, stage)
    if image:
        container["image"] = image
    if args is not None:
        container["args"] = args
    if provider:
        env = [item for item in container.get("env", []) if item.get("name") != "BRAIN"]
        container["env"] = [*env, {"name": "BRAIN", "value": provider}]
    return job

def _scraper_job(cron: dict[str, Any], run_id: str, image: str | None) -> dict[str, Any]:
    if cron.get("kind") != "CronJob" or cron.get("spec", {}).get("suspend") is not True:
        raise CoordinatorError("ScraperCronJobNotSuspended")
    try:
        source = {"kind": "Job", "spec": copy.deepcopy(cron["spec"]["jobTemplate"]["spec"])}
    except (KeyError, TypeError) as error:
        raise CoordinatorError("InvalidCronJob") from error
    return _prepare_job(source, "scraper", run_id, image)

def _create_and_wait(client: Kubectl, job: dict[str, Any], stage: str, receipts: dict[str, Any]) -> dict[str, Any]:
    name = job["metadata"]["name"]
    receipts[stage] = {"job_name": name, "creation_outcome": "unknown"}
    try:
        created = client.json(
            ["create", "-f", "-", "-n", NAMESPACE, "-o", "json"],
            json.dumps(job, separators=(",", ":")),
        )
    except CoordinatorError as error:
        if str(error) == "KubectlTimeout":
            raise CoordinatorError("JobCreationOutcomeUnknown") from error
        raise
    uid = created.get("metadata", {}).get("uid")
    if not isinstance(uid, str) or not uid:
        raise CoordinatorError("MissingJobUID")
    receipts[stage].update(job_uid=uid, creation_outcome="created")
    while True:
        observed_job = client.read_json(
            ["get", f"job/{name}", "-n", NAMESPACE, "-o", "json"]
        )
        metadata = observed_job.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("uid") != uid:
            raise CoordinatorError("JobUIDMismatch")
        status = observed_job.get("status", {})
        if status.get("succeeded") or status.get("failed"):
            break
        remaining = client.deadline - time.monotonic()
        if remaining <= 0:
            raise CoordinatorError("RunDeadlineExceeded")
        time.sleep(min(2, remaining))
    pods = client.read_json([
        "get", "pods", "-n", NAMESPACE, "-l", f"job-name={name}", "-o", "json",
    ]).get("items")
    if not isinstance(pods, list) or len(pods) != 1:
        raise CoordinatorError("AmbiguousJobPod")
    pod = pods[0]
    try:
        pod_name = pod["metadata"]["name"]
        pod_uid = pod["metadata"]["uid"]
        owners = pod["metadata"].get("ownerReferences")
        owns_pod = isinstance(owners, list) and any(
            isinstance(item, dict)
            and item.get("apiVersion") == "batch/v1"
            and item.get("kind") == "Job"
            and item.get("name") == name
            and item.get("uid") == uid
            for item in owners
        )
        states = pod["status"]["containerStatuses"]
        state = next(item for item in states if item.get("name") == stage)
        exit_code = state["state"]["terminated"]["exitCode"]
        image_id = state["imageID"]
    except (AttributeError, KeyError, StopIteration, TypeError) as error:
        raise CoordinatorError("IncompleteJobPod") from error
    if not isinstance(pod_uid, str) or not pod_uid or not owns_pod:
        raise CoordinatorError("JobPodOwnershipMismatch")
    receipts[stage].update(
        pod_name=pod_name, pod_uid=pod_uid, exit_code=exit_code, image_id=image_id,
    )
    logs = client.read_text([
        "logs", f"pod/{pod_name}", "-n", NAMESPACE, "-c", stage,
        "--tail=200", "--limit-bytes=1048576",
    ])
    return {
        "job_name": name, "job_uid": uid, "creation_outcome": "created",
        "pod_name": pod_name, "pod_uid": pod_uid,
        "exit_code": exit_code, "image_id": image_id, "logs": logs,
    }

def _summary(logs: str, required: set[str]) -> dict[str, Any]:
    lines = [line for line in logs.splitlines() if line.strip()]
    candidates = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required <= value.keys():
            candidates.append((line, value))
    if len(candidates) != 1 or not lines or candidates[0][0] != lines[-1]:
        raise CoordinatorError("InvalidReceipt")
    return candidates[0][1]

def _scraper_summary(logs: str) -> dict[str, Any]:
    value = _summary(logs, {
        "fetched_count", "matched_count", "new_count",
        "observed_posting_ids", "inserted_posting_ids",
    })
    if any(type(value[key]) is not int or value[key] < 0 for key in
           ("fetched_count", "matched_count", "new_count")):
        raise CoordinatorError("InvalidReceipt")
    observed, inserted = value["observed_posting_ids"], value["inserted_posting_ids"]
    try:
        valid = (
            isinstance(observed, list) and isinstance(inserted, list)
            and [str(UUID(item)) for item in observed] == observed
            and [str(UUID(item)) for item in inserted] == inserted
            and len(set(observed)) == len(observed) and set(inserted) <= set(observed)
            and len(set(inserted)) == len(inserted) == value["new_count"]
            and value["fetched_count"] >= value["matched_count"] >= len(observed)
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise CoordinatorError("InvalidReceipt")
    return value

def _model_summary(
    logs: str, outcome: str, *, posting_ids: Sequence[str] = (), limit: int | None = None,
) -> dict[str, Any]:
    value = _summary(logs, {"selected", outcome, "failed"})
    if any(type(value[key]) is not int or value[key] < 0 for key in
           ("selected", outcome, "failed")):
        raise CoordinatorError("InvalidReceipt")
    if value[outcome] + value["failed"] != value["selected"]:
        raise CoordinatorError("InvalidReceipt")
    requested = list(dict.fromkeys(posting_ids))
    if requested and limit is not None and len(requested) <= limit:
        selected = value.get("selected_posting_ids")
        skipped = value.get("skipped_posting_ids")
        try:
            valid = (
                isinstance(selected, list) and isinstance(skipped, list)
                and [str(UUID(item)) for item in selected] == selected
                and [str(UUID(item)) for item in skipped] == skipped
                and len(set(selected)) == len(selected) == value["selected"]
                and type(value.get("skipped")) is int
                and len(set(skipped)) == len(skipped) == value.get("skipped")
                and not set(selected) & set(skipped)
                and set(selected) | set(skipped) == set(requested)
            )
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise CoordinatorError("IncompleteReceipt")
    return value

def _receipt(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "cohort_count": None, "fetched": None, "matched": None,
        "new": None, "extracted": None, "scored": None,
        "selected_counts": {"extractor": None, "classifier": None},
        "skipped_counts": {"extractor": None, "classifier": None},
        "failures": [], "jobs": {},
        "count_meanings": {
            "fetched": "scraper ingestion activity before cheap gates",
            "matched": "scraper activity after cheap gates and before persistence dedupe",
            "new": "rows first inserted by this scraper run",
            "extracted_scored": (
                "completed work selected within this observed cohort; may finish prior observations "
                "and is not a new-only funnel or a nightly ten-minute performance claim"
            ),
        },
    }

def _fail(
    receipt: dict[str, Any], stage: str, error: BaseException, chunk: int | None = None,
) -> None:
    code = str(error) if isinstance(error, CoordinatorError) else type(error).__name__
    failure = {"stage": stage, "failure": code}
    if chunk is not None:
        failure["chunk"] = chunk
    receipt["failures"].append(failure)

def _run_all_observed(
    client: Kubectl, config: BatchConfig, run_id: str,
    observed: list[str], receipt: dict[str, Any],
) -> None:
    chunks = [observed[index:index + config.limit]
              for index in range(0, len(observed), config.limit)]
    receipt["chunk_count"] = len(chunks)
    receipt["jobs"].update(extractor=[], classifier=[])
    totals = {
        "extractor": {"selected": 0, "completed": 0, "failed": 0,
                      "skipped": 0, "reported_chunks": 0},
        "classifier": {"selected": 0, "completed": 0, "failed": 0,
                       "skipped": 0, "reported_chunks": 0},
    }
    lock = threading.Lock()

    def pipeline(chunk_number: int, posting_ids: list[str]) -> None:
        model_args = [
            "--limit", str(len(posting_ids)),
            "--timeout-seconds", str(config.timeout_seconds),
        ]
        for posting_id in posting_ids:
            model_args.extend(("--posting-id", posting_id))
        for stage, outcome, image, provider in (
            ("extractor", "extracted", config.extractor_image, config.extractor_provider),
            ("classifier", "scored", config.classifier_image, config.classifier_provider),
        ):
            partial: dict[str, Any] = {}
            result = None
            summary = None
            failure = None
            job_name = f"{stage}-{run_id}-{chunk_number:03d}"
            try:
                template = client.json([
                    "create", "-f", str(REPO_ROOT / "k8s" / f"{stage}-job.yaml"),
                    "--dry-run=client", "-n", NAMESPACE, "-o", "json",
                ])
                job = _prepare_job(
                    template, stage, run_id, image, model_args, provider,
                    chunk=chunk_number,
                )
                result = _create_and_wait(client, job, stage, partial)
                summary = _model_summary(
                    result["logs"], outcome,
                    posting_ids=posting_ids, limit=len(posting_ids),
                )
                if result["exit_code"] != 0:
                    raise CoordinatorError("JobFailed")
            except Exception as error:
                failure = error
            with lock:
                job_receipt = result or partial.get(stage) or {
                    "job_name": job_name, "not_created": True,
                }
                job_receipt.update(chunk=chunk_number, posting_ids=posting_ids)
                receipt["jobs"][stage].append(job_receipt)
                if summary is not None:
                    totals[stage]["selected"] += summary["selected"]
                    totals[stage]["completed"] += summary[outcome]
                    totals[stage]["failed"] += summary["failed"]
                    totals[stage]["skipped"] += summary["skipped"]
                    totals[stage]["reported_chunks"] += 1
                if failure is not None:
                    _fail(receipt, stage, failure, chunk_number)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(pipeline, number, chunk): number
            for number, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                with lock:
                    _fail(receipt, "pipeline", error, futures[future])

    receipt["aggregate_receipts"] = {}
    for stage, outcome in (("extractor", "extracted"), ("classifier", "scored")):
        receipt["jobs"][stage].sort(key=lambda item: item["chunk"])
        aggregate = totals[stage]
        complete = aggregate["reported_chunks"] == len(chunks)
        receipt["aggregate_receipts"][stage] = {
            **aggregate, "chunk_count": len(chunks), "complete": complete,
        }
        receipt["selected_counts"][stage] = aggregate["selected"] if complete else None
        receipt["skipped_counts"][stage] = aggregate["skipped"] if complete else None
        receipt[outcome] = aggregate["completed"] if complete else None
    receipt["failures"].sort(key=lambda item: (item.get("chunk", -1), item["stage"]))

def run_cohort(
    config: BatchConfig, *, kubectl: Callable[..., str] = _run, run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or (
        f"funnel-{datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz')}-{uuid4().hex[:8]}"
    )
    if len(run_id) > 45 or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run ID must be a lowercase Kubernetes label value")
    client, receipt = Kubectl(kubectl), _receipt(run_id)
    if config.all_observed:
        receipt.update(mode="all_observed", chunk_count=0)
    try:
        cron = client.json(["get", "cronjob/scraper", "-n", NAMESPACE, "-o", "json"])
        job = _scraper_job(cron, run_id, config.scraper_image)
        scraper = _create_and_wait(client, job, "scraper", receipt["jobs"])
        receipt["jobs"]["scraper"] = scraper
        if scraper["exit_code"] != 0:
            raise CoordinatorError("JobFailed")
        summary = _scraper_summary(scraper["logs"])
    except Exception as error:
        _fail(receipt, "scraper", error)
        receipt["jobs"].update(
            extractor={"skipped": "scraper_failure"}, classifier={"skipped": "scraper_failure"}
        )
        return receipt
    observed = summary["observed_posting_ids"]
    receipt.update(
        cohort_count=len(observed), fetched=summary["fetched_count"],
        matched=summary["matched_count"], new=summary["new_count"],
    )
    if not observed:
        receipt.update(extracted=0, scored=0)
        receipt["selected_counts"] = {"extractor": 0, "classifier": 0}
        receipt["skipped_counts"] = {"extractor": 0, "classifier": 0}
        receipt["jobs"].update(
            extractor={"skipped": "empty_cohort"}, classifier={"skipped": "empty_cohort"}
        )
        return receipt
    if config.all_observed:
        _run_all_observed(client, config, run_id, observed, receipt)
        return receipt
    model_args = ["--limit", str(config.limit), "--timeout-seconds", str(config.timeout_seconds)]
    for posting_id in observed:
        model_args.extend(("--posting-id", posting_id))
    for stage, outcome, image, provider in (
        ("extractor", "extracted", config.extractor_image, config.extractor_provider),
        ("classifier", "scored", config.classifier_image, config.classifier_provider),
    ):
        try:
            template = client.json([
                "create", "-f", str(REPO_ROOT / "k8s" / f"{stage}-job.yaml"),
                "--dry-run=client", "-n", NAMESPACE, "-o", "json",
            ])
            job = _prepare_job(template, stage, run_id, image, model_args, provider)
            result = _create_and_wait(client, job, stage, receipt["jobs"])
            receipt["jobs"][stage] = result
            summary = _model_summary(
                result["logs"], outcome, posting_ids=observed, limit=config.limit,
            )
            receipt["selected_counts"][stage] = summary["selected"]
            receipt["skipped_counts"][stage] = summary.get("skipped")
            receipt[outcome] = summary[outcome]
            if result["exit_code"] != 0:
                raise CoordinatorError("JobFailed")
        except Exception as error:
            _fail(receipt, stage, error)
    return receipt

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, choices=range(1, 31), default=1)
    parser.add_argument("--timeout-seconds", type=int, choices=range(1, 121), default=120)
    for stage in ("scraper", "extractor", "classifier"):
        parser.add_argument(f"--{stage}-image")
    for stage in ("extractor", "classifier"):
        parser.add_argument(f"--{stage}-provider", choices=("ollama", "codex"))
    parser.add_argument("--all-observed", action="store_true")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    receipt = run_cohort(BatchConfig(**vars(build_parser().parse_args(argv))))
    print(json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 1 if receipt["failures"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
