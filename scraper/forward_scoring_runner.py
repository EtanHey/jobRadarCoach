"""Prepare, execute, resume, and report the approved forward-scoring run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scraper import forward_scoring_runtime as runtime
from scraper.forward_scoring_harness import (
    FIXED_FLOOR,
    canonical_json,
    jev_prediction,
    reference_prediction,
)
from scraper.forward_scoring_inputs import materialize_manifest
from scraper.forward_scoring_policy import render_report, summarize_forward

PROVIDER_GATE = "JRC_FORWARD_SCORING_APPROVED_FREEZE_SHA256"
ROOT = Path(__file__).resolve().parents[1]
RUN_LEDGER_DIR = ROOT / ".run-state" / "forward-scoring-40"


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise TypeError("forward manifest must be an object")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def freeze_sha(manifest: Mapping[str, Any]) -> str:
    runtime.validate_frozen(manifest)
    receipt = manifest["freeze_receipt"]
    if receipt.get("algorithm") != "sha256" or not isinstance(
        receipt.get("sha256"), str
    ):
        raise ValueError("invalid freeze receipt")
    return receipt["sha256"]


def run_sha(manifest: Mapping[str, Any]) -> str:
    rows = runtime.validate_frozen(manifest)
    results = []
    for row in rows:
        if not isinstance(row.get("reference"), Mapping) or len(row["jev"]) != 1:
            raise ValueError("run is incomplete")
        results.append(
            {
                "locator": row["locator"],
                "reference": row["reference"],
                "jev": row["jev"][0],
            }
        )
    return _sha({"freeze_sha256": freeze_sha(manifest), "run": 1, "results": results})


def prepare(manifest_path: Path, **options: object) -> dict[str, Any]:
    manifest = materialize_manifest(**options)
    runtime.validate_frozen(manifest)
    manifest["execution"] = runtime.execution_metadata()
    write_json(manifest_path, manifest)
    return manifest


def tls_ca_bundle() -> Path:
    """Resolve and validate the CA file urllib will use for the Jev call."""

    explicit = os.getenv("SSL_CERT_FILE")
    defaults = ssl.get_default_verify_paths()
    candidates = (
        [Path(explicit)]
        if explicit
        else [
            Path(value)
            for value in (
                defaults.cafile,
                defaults.openssl_cafile,
                "/etc/ssl/cert.pem",
                "/etc/ssl/certs/ca-certificates.crt",
                "/opt/homebrew/etc/openssl@3/cert.pem",
            )
            if value
        ]
    )
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            context = ssl.create_default_context(cafile=str(candidate))
        except (OSError, ssl.SSLError):
            continue
        if context.cert_store_stats().get("x509_ca", 0) > 0:
            return candidate.resolve()
    source = "configured" if explicit else "system"
    raise ValueError(f"no valid {source} TLS CA bundle is available")


@contextmanager
def _provider_environment(ca_bundle: Path) -> Iterator[None]:
    values = runtime.provider_environment()
    values["SSL_CERT_FILE"] = str(ca_bundle)
    prior = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _finite_cost(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("recorded Jev cost must be finite and non-negative")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("recorded Jev cost must be finite and non-negative")
    return result


def execute(
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    reference_runner=None,
    jev_transport=None,
) -> None:
    rows = runtime.validate_frozen(manifest)
    receipt_sha = freeze_sha(manifest)
    if os.getenv(PROVIDER_GATE) != receipt_sha:
        raise RuntimeError(
            f"provider execution is held; set {PROVIDER_GATE} to the approved freeze SHA"
        )
    if manifest.get("execution") != runtime.execution_metadata():
        raise ValueError("execution metadata does not match the approved runtime")

    run_receipt = manifest.get("run_receipt")
    started = any(
        "reference" in row or row.get("jev_attempt") is not None or row["jev"]
        for row in rows
    )
    if run_receipt is None:
        if started:
            raise ValueError("run state exists without a durable run receipt")
    elif (
        not isinstance(run_receipt, Mapping)
        or run_receipt.get("run") != 1
        or run_receipt.get("freeze_sha256") != receipt_sha
    ):
        raise ValueError("run receipt does not match the approved frozen run")
    elif "run_sha256" in run_receipt:
        raise RuntimeError("the approved run is already complete")

    blocked_jev = [
        row for row in rows if row.get("jev_attempt") == {"run": 1} and not row["jev"]
    ]
    if blocked_jev:
        raise RuntimeError("a Jev row was already attempted; retries are forbidden")
    pending_jev = [row for row in rows if not row["jev"]]
    spent = sum(_finite_cost(item["cost_usd"]) for row in rows for item in row["jev"])
    maximum_remaining = len(pending_jev) * runtime.jev_client.maximum_call_cost()
    if spent + maximum_remaining > runtime.REMAINING_CAP_USD:
        raise RuntimeError("maximum planned Jev cost exceeds the remaining lane cap")
    ca_bundle = tls_ca_bundle()

    remaining_reference = sum("reference" not in row for row in rows)
    print(
        canonical_json(
            {
                "event": "provider_preflight",
                "freeze_sha256": receipt_sha,
                "reference_calls": remaining_reference,
                "jev_calls": len(pending_jev),
                "maximum_jev_cost_usd": maximum_remaining,
                "recorded_jev_cost_usd": spent,
                "lane_cap_usd": runtime.CAP_USD,
                "incident_reservation_usd": runtime.INCIDENT_RESERVATION_USD,
                "remaining_experiment_cap_usd": runtime.REMAINING_CAP_USD,
                "run_ledger_dir": str(RUN_LEDGER_DIR),
                "tls_ca_bundle": str(ca_bundle),
                **runtime.execution_metadata(),
            }
        ),
        flush=True,
    )
    if run_receipt is None:
        manifest["run_receipt"] = {"run": 1, "freeze_sha256": receipt_sha}
    write_json(manifest_path, manifest)

    for row in rows:
        if "reference" not in row:
            if reference_runner is None:
                row["reference"] = runtime.score_reference(row)
            else:
                row["reference"] = runtime.score_reference(row, reference_runner)
            write_json(manifest_path, manifest)

    with _provider_environment(ca_bundle):
        for row in pending_jev:
            row["jev_attempt"] = {"run": 1}
            write_json(manifest_path, manifest)
            row["jev"].append(runtime.score_jev(row, RUN_LEDGER_DIR, jev_transport))
            write_json(manifest_path, manifest)

    summarize_forward(manifest)
    manifest["run_receipt"]["run_sha256"] = run_sha(manifest)
    write_json(manifest_path, manifest)


def _prediction(row: Mapping[str, Any]) -> tuple[str, str, str]:
    gold = row["gold"]["label"]
    reference = reference_prediction(row["reference"]["fit_score"])
    observation = row["jev"][0]
    jev = jev_prediction(observation["answer"], observation["confidence"], FIXED_FLOOR)
    return gold, reference, jev


def render_final_report(manifest: Mapping[str, Any]) -> str:
    report = render_report(manifest).rstrip()
    freeze, run = freeze_sha(manifest), run_sha(manifest)
    lines = [
        report,
        "",
        "## Run identity",
        "",
        f"- Freeze SHA-256: `{freeze}`",
        f"- Run SHA-256: `{run}`",
        "- Run count: 1 (no pooled reruns)",
        f"- Approved experiment-only deviation: `{runtime.EXPERIMENT_CODEX_VERSION}` with model `{runtime.REFERENCE_MODEL}`; production pin `{runtime.SUPPORTED_CODEX_CLI_VERSION}` remains unchanged.",
        "",
        "## Per-row disagreement ledger",
        "",
        "| Part | Locator | Posting | Gold | Reference | Jev |",
        "|---:|---|---|---|---|---|",
    ]
    disagreements = 0
    for row in manifest["rows"]:
        gold, reference, jev = _prediction(row)
        if len({gold, reference, jev}) == 1:
            continue
        disagreements += 1
        posting = row["frozen_input"]["hosted_payload"]["public_posting"]
        values = (
            row["part"],
            row["locator"],
            f"{posting['company']} — {posting['title']}",
            gold,
            reference,
            jev,
        )
        lines.append(
            "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"
        )
    if not disagreements:
        lines.append("| — | — | No disagreements | — | — | — |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subcommands.add_parser("prepare")
    prepare_parser.add_argument("manifest", type=Path)
    prepare_parser.add_argument("--database-url", required=True)
    execute_parser = subcommands.add_parser("execute")
    execute_parser.add_argument("manifest", type=Path)
    report_parser = subcommands.add_parser("report")
    report_parser.add_argument("manifest", type=Path)
    report_parser.add_argument("output", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "prepare":
        prepare(
            arguments.manifest,
            part1_answers=Path.home()
            / "Downloads/2026-09-22-forward-test-completed.md",
            part1_mapping=ROOT / "docs.local/forward-test/2026-09-22-mapping.json",
            part2_answers=ROOT / "docs.local/forward-test/2026-09-22-part2-answers.md",
            part2_mapping=ROOT
            / "docs.local/forward-test/2026-09-22-part2-mapping.json",
            part3_answers=ROOT / "docs.local/forward-test/2026-09-22-part3-answers.md",
            part3_mapping=ROOT
            / "docs.local/forward-test/2026-09-22-part3-mapping.json",
            database_url=arguments.database_url,
        )
    elif arguments.command == "execute":
        manifest = load_manifest(arguments.manifest)
        execute(manifest, arguments.manifest)
    else:
        write_text(
            arguments.output, render_final_report(load_manifest(arguments.manifest))
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
