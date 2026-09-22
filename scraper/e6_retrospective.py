#!/usr/bin/env python3
"""E6 retrospective: shadow-only Jev decisions versus stored fit scores.

The executable is deliberately read-only with respect to Job Radar's database.
It parses Etan-authored verdicts from the cited E6 source tables, joins them to
scored postings, runs Jev in shadow mode, and emits machine-readable receipts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import re
import statistics
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import psycopg

from classifier import core, projection
from scraper.annotate import (
    _codex_exec_command,
    _discover_codex,
    _isolated_codex_environment,
    _subscription_auth_path,
)
from scraper.brain import run_brain


ROOT = Path(__file__).resolve().parents[1]
GOLEMS = Path.home() / "Gits/golems"
SHARED_JEV = GOLEMS / "packages/shared/src/lib/jev.py"
SOURCE_ROOT = Path.home() / "Gits/orchestrator/docs.local/research/jev-phase0"
SOURCE_C = SOURCE_ROOT / "E6-source-C-verdicts-2026-09.md"
SOURCE_D = SOURCE_ROOT / "E6-source-D-verdicts-2026-06-08.md"
DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
SITE = "jrc-e6-retrospective"
RUNS = 3
FLOORS = tuple(value / 100 for value in range(50, 100, 5))
FIXED_FLOOR = 0.70
RESERVE_USD = 0.50
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
SAMPLE_SEED = 20260922
JUDGE_MODEL = "gpt-6-astra"


@dataclass(frozen=True)
class GoldVerdict:
    source_file: str
    source_row: int
    company: str
    role: str
    verdict_text: str
    label: str
    ownership: str
    currency: str
    citation: str
    gate: bool
    radar_scraped: bool


@dataclass(frozen=True)
class Posting:
    id: str
    external_id: str | None
    url: str
    title: str
    company: str
    location: str
    raw_jd: str
    score_payload: dict[str, Any]
    brain: str
    model: str


@dataclass(frozen=True)
class JoinedGold:
    verdict: GoldVerdict
    posting: Posting
    join_method: str


NEVER_SCRAPED = {
    "check point", "palo alto", "palo alto networks", "era born", "orca",
    "orca fund os", "herdr", "dondy", "shop circle", "yara ai", "anyura",
    "workday", "air space intelligence", "asi", "jakoai", "yara",
}

GATE_KEYS = {
    ("navan", "backend engineer ai solutions"),
    ("supabase", "frontend engineer"),
    ("nice", "software engineer"),
    ("pentera", "lead ai transformation engineer"),
    ("simplex 3d", "ai engineer"),
    ("check point", "sw dev cyber security ai agents"),
    ("palo alto", "experienced backend engineer cortex xsoar"),
    ("palo alto", "senior angular frontend engineer email security"),
    ("abra", "c net role"),
    ("avatrade", ""),
    ("balance", "full stack engineer credit"),
}

# Source-specific final-state corrections. These prevent silence, employer
# outcomes, unresolved contradictions, and superseded states becoming gold.
EXCLUDE_KEYS = {
    ("Sett", "AI Fullstack Engineer"),
    ("Canditech", "Full Stack Engineer (AI-First)"),
    ("Xpend", "Full Stack SWE (AI Automation)"),
    ("Gotfriends", "AI Engineer"),
    ("ASI", "Frontend (Boston)"),
    ("Ashley Digital", "—"),  # superseded by the 09-17 ResidentHome decline
    ("CISO 99, Upware, Tadata", "founder outreach (Shushu)"),  # outreach batch, not one posting verdict
    ("El Al / אופק", "—"),  # eligibility hold, not a professional-fit verdict
    ("Jeen.ai", "phone screen (Mor Barhum)"),  # process event for the already-counted application
    ("מוקד אמון", "guarding"),  # commute closure, outside the fit-scorer population
}
POSITIVE_OVERRIDES = {
    ("Jeen.ai", "AI Solution Engineer"),
    ("Balance", "Full-Stack, Credit"),
    ("Daylight Security", "Senior Full Stack"),
    ("Bridgeify", "—"),
}
NEGATIVE_OVERRIDES = {
    ("Yara AI", "(AI eng, 2 founders)"),
    ("Anyura", "(eng, 2 founders, 50-60h)"),
    ("Workday", "Full Stack SWE, Agent Platform (Boulder hybrid)"),
    ("Ashley Digital / ResidentHome", "(FS role via Yariv)"),
}

KNOWN_EXTERNAL_IDS = {
    ("rej", "full stack ai engineer madrid remote"): "4466461824",
    ("doit", "full stack engineer cloud and saas integrations"): "4463965907",
    ("shop circle", "software engineer"): "4467736120",
    ("centrical", "ai platform engineer"): "4468254008",
    ("windward", "applied ai engineer"): "4459194800",
    ("stigg", "full stack engineer"): "4465908530",
    ("wix", "ai engineer marketing ai transformation"): "4464473262",
    ("nice", "software engineer"): "4463483720",
    ("pentera", "ai transformation engineer"): "4462220726",
    ("simplex 3d", "ai engineer"): "4462508593",
    ("yad2", "full stack developer"): "4460672969",
}


def _load_path_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_tls_ca_bundle() -> str:
    """Use the interpreter's certifi roots when macOS Python has no system CA."""
    if os.environ.get("SSL_CERT_FILE"):
        return os.environ["SSL_CERT_FILE"]
    try:
        import certifi
    except ImportError as error:
        raise RuntimeError("SSL_CERT_FILE is unset and certifi is unavailable") from error
    os.environ["SSL_CERT_FILE"] = certifi.where()
    return os.environ["SSL_CERT_FILE"]


def _markdown_rows(path: Path) -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|") or re.match(r"^\|[-:| ]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0].casefold() not in {"company", "#", "item", "feedback"}:
            rows.append((line_number, cells))
    return rows


def _plain(value: str) -> str:
    value = re.sub(r"[*_`]", "", value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _company_key(value: str) -> str:
    value = _plain(value).casefold().replace("&", " and ")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(?:software|security|networks?|ai|ltd|inc|group)\b", " ", value)
    aliases = {
        "real estate in jeans": "rej", "real estate in jeans rej": "rej", "palo alto": "palo alto",
        "check point": "check point", "air space intelligence": "asi",
        "shop circle": "shop circle", "dondy shop circle": "shop circle",
        "nice": "nice", "jeen": "jeen", "jeen ai": "jeen",
    }
    compact = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return aliases.get(compact, compact)


def _title_key(value: str) -> str:
    value = _plain(value).casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b(?:senior|junior|sr|jr|lead|experienced|core|product|team)\b", " ", value)
    value = value.replace("full-stack", "full stack").replace("fullstack", "full stack")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _is_gate(company: str, role: str) -> bool:
    key = (_company_key(company), _title_key(role))
    if key in GATE_KEYS:
        return True
    company_key, role_key = _company_key(company), _title_key(role)
    if company_key == "navan" and "java" in _plain(role + " " + company).casefold():
        return True
    if company_key == "palo alto" and any(term in role_key for term in ("backend", "angular")):
        return True
    if company_key == "balance":
        return True
    if re.search(r"\b(?:staff|principal|head of|head-of|lead)\b", role_key):
        return True
    text = f"{company_key} {role_key}"
    return any(token in text for token in (
        "supabase frontend", "nice engineer", "simplex 3d engineer",
        "pentera ai transformation", "check point cyber agents",
        "palo alto backend cortex xsoar", "palo alto angular frontend",
        "navan backend", "balance full stack engineer credit", "abra", "avatrade",
    ))


def _label(company: str, role: str, verdict: str, ownership: str) -> str | None:
    key = (_plain(company), _plain(role))
    if key in EXCLUDE_KEYS or not re.search(r"\bHIS\b", ownership):
        return None
    if key in POSITIVE_OVERRIDES:
        return "positive"
    if key in NEGATIVE_OVERRIDES:
        return "negative"
    text = _plain(verdict).casefold()
    if "conflict" in text or "no verdict" in text or "no action" in text:
        return None
    # Final action wins over earlier doubt or a later employer rejection.
    if any(term in text for term in (
        "applied", "referred", "referral sent", "reopened", "advanced",
        "resume sent", "messages sent", "replied interested", "judged best fit",
        "fits great", "warm lead", "screened", "interviewed",
    )):
        return "positive"
    if any(term in text for term in (
        "skipped", "declined", "parked", "dropped", "rejected/closed",
        "closed — shift", "on hold",
    )):
        return "negative"
    return None


def load_gold(source_c: Path = SOURCE_C, source_d: Path = SOURCE_D) -> tuple[list[GoldVerdict], list[dict[str, str]]]:
    gold: list[GoldVerdict] = []
    excluded: list[dict[str, str]] = []
    for path, width in ((source_c, 7), (source_d, 7)):
        for line_number, cells in _markdown_rows(path):
            if len(cells) != width:
                continue
            company, role, verdict, words, date, citation, final = map(_plain, cells)
            ownership = verdict if path == source_c else final
            label = _label(company, role, verdict, ownership)
            if label is None:
                excluded.append({"company": company, "role": role, "reason": "not final Etan-authored gold"})
                continue
            currency = final if path == source_c else "final row state"
            gold.append(GoldVerdict(
                path.name, line_number, company, role, verdict, label, ownership,
                currency, citation, _is_gate(company, role),
                _company_key(company) not in NEVER_SCRAPED,
            ))
    # C is newer than D. Remove older same-company states when C carries a final
    # verdict, while preserving distinct roles at the same employer.
    newest: dict[tuple[str, str], GoldVerdict] = {}
    for verdict in sorted(gold, key=lambda row: (row.source_file != source_c.name, row.source_row)):
        key = (_company_key(verdict.company), _title_key(verdict.role))
        newest.setdefault(key, verdict)
    return sorted(newest.values(), key=lambda row: (row.company.casefold(), row.role.casefold())), excluded


def load_scored_postings(connection) -> list[Posting]:
    rows = connection.execute(
        "select p.id::text,p.external_id,p.url,p.title,p.company,p.location,p.raw_jd,"
        "s.score_payload,s.brain,s.model from public.postings p join public.posting_scores s "
        "on s.posting_id=p.id order by p.id"
    ).fetchall()
    return [Posting(
        str(row[0]), row[1], str(row[2] or ""), str(row[3]), str(row[4]),
        str(row[5] or ""), str(row[6]), dict(row[7]), str(row[8]), str(row[9]),
    ) for row in rows]


def load_profile_snapshot(connection) -> dict[str, object]:
    return {str(field): value for field, value in connection.execute(
        "select field,value from public.profile order by field"
    ).fetchall()}


def _similarity(verdict: GoldVerdict, posting: Posting) -> float:
    vc, pc = _company_key(verdict.company), _company_key(posting.company)
    company = SequenceMatcher(None, vc, pc).ratio()
    if vc and pc and min(len(vc), len(pc)) >= 5 and (vc in pc or pc in vc):
        company = max(company, 0.95)
    vt, pt = _title_key(verdict.role), _title_key(posting.title)
    a, b = set(vt.split()), set(pt.split())
    title = len(a & b) / len(a | b) if a and b else 0.0
    return 0.60 * company + 0.40 * title


def join_gold(gold: Sequence[GoldVerdict], postings: Sequence[Posting]) -> tuple[list[JoinedGold], list[GoldVerdict]]:
    joined: list[JoinedGold] = []
    unjoined: list[GoldVerdict] = []
    used: set[str] = set()
    for verdict in gold:
        source_text = f"{verdict.role} {verdict.citation}"
        ids = set(re.findall(r"(?<!\d)\d{9,12}(?!\d)", source_text))
        known_id = KNOWN_EXTERNAL_IDS.get((_company_key(verdict.company), _title_key(verdict.role)))
        if known_id:
            ids.add(known_id)
        exact = [row for row in postings if row.id not in used and (
            (row.external_id and row.external_id in ids) or any(item in row.url for item in ids)
        )]
        if len(exact) == 1:
            match, method = exact[0], "external-id/url"
        else:
            ranked = sorted(
                ((round(_similarity(verdict, row), 6), row) for row in postings if row.id not in used),
                key=lambda item: (item[0], item[1].id), reverse=True,
            )
            top_title = 0.0
            if ranked:
                left, right = set(_title_key(verdict.role).split()), set(_title_key(ranked[0][1].title).split())
                top_title = len(left & right) / len(left | right) if left and right else 0.0
            top_company = SequenceMatcher(None, _company_key(verdict.company), _company_key(ranked[0][1].company)).ratio() if ranked else 0.0
            if not ranked or ranked[0][0] < 0.72 or top_company < 0.80 or top_title < 0.45 or (
                len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.04
            ):
                unjoined.append(verdict)
                continue
            match, method = ranked[0][1], f"normalized-company-title:{ranked[0][0]:.3f}"
        used.add(match.id)
        joined.append(JoinedGold(verdict, match, method))
    return joined, unjoined


def jev_question() -> dict[str, object]:
    return {
        "id": "pursuit_decision", "type": "choice",
        "instructions": (
            "Would this candidate pursue this exact posting now? Judge professional fit only "
            "from the supplied cloud-safe profile and public posting. Return one choice."
        ),
        "criteria": {
            "pursue": "Strong enough to apply, seek a referral, or actively continue.",
            "maybe": "Plausible but materially uncertain; needs human review.",
            "no": "A material mismatch makes pursuit unwarranted.",
        },
        "fallback_answer": "maybe",
    }


def jev_state(posting: Posting, professional_profile: dict[str, object]) -> dict[str, object]:
    public = projection.public_posting({
        "id": posting.id, "title": posting.title, "company": posting.company,
        "location": posting.location, "raw_jd": posting.raw_jd,
    })
    return {"professional_profile": professional_profile, "public_posting": public}


def jev_sanitizer(state: object) -> object:
    if not isinstance(state, dict) or set(state) != {"professional_profile", "public_posting"}:
        raise ValueError("E6 state contains unsupported fields")
    profile = state["professional_profile"]
    posting = state["public_posting"]
    if not isinstance(profile, dict) or not isinstance(posting, dict):
        raise ValueError("E6 state is malformed")
    # Reconstructing through the same public projection protects against caller
    # additions. The professional object was produced by profile_contract.
    projected = projection.public_posting({
        "id": posting.get("id"), "title": posting.get("title"),
        "company": posting.get("company"), "location": posting.get("location"),
        "raw_jd": posting.get("jd_text"),
    })
    if projected != posting:
        raise ValueError("E6 posting projection changed")
    return {"professional_profile": profile, "public_posting": projected}


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def planned_cost(postings: Iterable[Posting], profile: dict[str, object], calls_by_id: Mapping[str, int]) -> float:
    question = jev_question()
    total_bytes = 0
    for posting in postings:
        payload = {
            "state": jev_state(posting, profile), "model": "jev-latest",
            "questions": {question["id"]: {key: value for key, value in question.items() if key not in {"id", "fallback_answer"}}},
        }
        total_bytes += len(canonical_json(payload).encode()) * calls_by_id.get(posting.id, 0)
    # One UTF-8 byte per token is deliberately conservative for the preflight.
    return total_bytes * PRICE_PER_INPUT_TOKEN


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def score_jev(client, posting: Posting, profile: dict[str, object], state_dir: Path, timeout: float) -> dict[str, Any]:
    usage_path = state_dir / "usage.jsonl"
    before = usage_path.stat().st_size if usage_path.exists() else 0
    started = time.monotonic()
    answers = client.jev_shadow(
        jev_state(posting, profile), [jev_question()], jev_sanitizer,
        site=SITE, state_dir=state_dir, timeout_seconds=timeout,
    )
    wall = time.monotonic() - started
    if len(answers) != 1:
        raise RuntimeError("Jev returned an incomplete answer")
    answer = answers[0]
    if answer.get("source") != "jev" or answer.get("acted") is not False:
        rows = _read_jsonl(state_dir / "decisions.jsonl")
        reason = rows[-1].get("fallback_reason") if rows else "unknown"
        raise RuntimeError(f"Jev fallback: {reason}")
    delta = [json.loads(line) for line in usage_path.read_bytes()[before:].decode().splitlines() if line]
    reservations = [row for row in delta if row.get("kind") == "reservation"]
    reconciliations = [row for row in delta if row.get("kind") == "reconciliation"]
    if len(reservations) != 1 or len(reconciliations) != 1 or reservations[0]["reservation_id"] != reconciliations[0]["reservation_id"]:
        raise RuntimeError("Jev usage reservation was not exactly reconciled")
    return {
        "answer": answer["answer"], "confidence": answer["confidence"],
        "probabilities": answer.get("probabilities", {}), "wall_seconds": wall,
        "model": reconciliations[0].get("model", "unknown"),
        "input_tokens": reconciliations[0]["input_tokens"],
        "cost_usd": sum(float(row["cost_usd"]) for row in delta),
    }


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


def _prediction(answer: str, confidence: float, floor: float) -> str:
    return answer if confidence >= floor else "abstain"


def _terra_choice(payload: Mapping[str, object]) -> str:
    recommendation = str(payload.get("recommendation", ""))
    return {"apply": "pursue", "referral": "pursue", "review": "maybe", "skip": "no"}.get(recommendation, "maybe")


def gold_metrics(rows: Sequence[dict[str, Any]], floor: float) -> dict[str, Any]:
    positives = [row for row in rows if row["gold"] == "positive"]
    negatives = [row for row in rows if row["gold"] == "negative"]
    tp = sum(_prediction(row["answer"], row["confidence"], floor) == "pursue" for row in positives)
    fp = sum(_prediction(row["answer"], row["confidence"], floor) == "pursue" for row in negatives)
    predicted_positive = tp + fp
    return {
        "positive_n": len(positives), "negative_n": len(negatives), "tp": tp, "fp": fp,
        "recall": tp / len(positives) if positives else 0.0,
        "recall_wilson_95": wilson(tp, len(positives)),
        "precision": tp / predicted_positive if predicted_positive else 0.0,
        "precision_wilson_95": wilson(tp, predicted_positive),
        "false_pursue_rate": fp / len(negatives) if negatives else 0.0,
        "false_pursue_wilson_95": wilson(fp, len(negatives)),
        "abstentions": sum(_prediction(row["answer"], row["confidence"], floor) == "abstain" for row in rows),
    }


def terra_metrics(joined: Sequence[JoinedGold]) -> dict[str, Any]:
    positives = [row for row in joined if row.verdict.label == "positive"]
    negatives = [row for row in joined if row.verdict.label == "negative"]
    tp = sum(_terra_choice(row.posting.score_payload) == "pursue" for row in positives)
    fp = sum(_terra_choice(row.posting.score_payload) == "pursue" for row in negatives)
    predicted_positive = tp + fp
    return {
        "positive_n": len(positives), "negative_n": len(negatives), "tp": tp, "fp": fp,
        "recall": tp / len(positives) if positives else 0.0,
        "recall_wilson_95": wilson(tp, len(positives)),
        "precision": tp / predicted_positive if predicted_positive else 0.0,
        "precision_wilson_95": wilson(tp, predicted_positive),
        "false_pursue_rate": fp / len(negatives) if negatives else 0.0,
        "false_pursue_wilson_95": wilson(fp, len(negatives)),
    }


def sample_divergences(rows: Sequence[dict[str, Any]], *, size: int = 60, seed: int = SAMPLE_SEED) -> tuple[list[dict[str, Any]], int]:
    population = [row for row in rows if row["jev_prediction"] != row["terra_prediction"]]
    selected = random.Random(seed).sample(population, min(size, len(population)))
    blind: list[dict[str, Any]] = []
    rng = random.Random(seed + 1)
    for row in selected:
        pair = [row["jev_prediction"], row["terra_prediction"]]
        rng.shuffle(pair)
        blind.append({
            "posting_id": row["posting_id"], "public_posting": row["public_posting"],
            "option_a": pair[0], "option_b": pair[1],
            "jev_option": "A" if pair[0] == row["jev_prediction"] else "B",
        })
    return blind, len(population)


def blind_adjudicate(
    blind: Sequence[dict[str, Any]], professional_profile: dict[str, object], *,
    batch_size: int = 15, timeout_seconds: float = 600,
) -> dict[str, Any]:
    """Ask an isolated Codex judge to choose between anonymized A/B decisions."""
    if not blind:
        return {"model": JUDGE_MODEL, "rows": [], "jev_wins": 0, "terra_wins": 0, "ties": 0}
    schema = {
        "type": "object", "additionalProperties": False, "required": ["decisions"],
        "properties": {"decisions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["posting_id", "choice", "rationale"],
            "properties": {
                "posting_id": {"type": "string"},
                "choice": {"type": "string", "enum": ["A", "B", "TIE"]},
                "rationale": {"type": "string"},
            },
        }}},
    }
    secret = {str(row["posting_id"]): str(row["jev_option"]) for row in blind}
    public_rows = [{key: value for key, value in row.items() if key != "jev_option"} for row in blind]
    judged: list[dict[str, Any]] = []
    codex = _discover_codex()
    auth = _subscription_auth_path()
    for offset in range(0, len(public_rows), batch_size):
        batch = public_rows[offset:offset + batch_size]
        with tempfile.TemporaryDirectory(prefix="jrc-e6-judge-") as temp:
            root = Path(temp)
            workspace, codex_home = root / "workspace", root / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()
            (codex_home / "auth.json").symlink_to(auth)
            schema_path, output_path = workspace / "schema.json", workspace / "result.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            prompt = "\n".join([
                "You are an independent blind judge of job-pursuit decisions.",
                "For each case choose A, B, or TIE based only on the cloud-safe professional profile and public posting.",
                "You are not told which system produced either option. Treat abstain as no confident decision, not as a hidden label.",
                "Return one decision for every posting_id exactly once.",
                "Professional profile:", canonical_json(professional_profile),
                "Blind cases:", canonical_json(batch),
            ])
            command = _codex_exec_command(
                codex, workspace=workspace, schema_path=schema_path, output_path=output_path,
                model=JUDGE_MODEL, reasoning_effort="medium",
            )
            completed = subprocess.run(
                command, input=prompt, text=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=timeout_seconds, cwd=workspace,
                env=_isolated_codex_environment(codex_home), check=False,
            )
            if completed.returncode != 0 or not output_path.exists():
                raise RuntimeError(f"blind judge failed with exit code {completed.returncode}")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            decisions = payload.get("decisions")
            if not isinstance(decisions, list) or {row.get("posting_id") for row in decisions} != {row["posting_id"] for row in batch}:
                raise RuntimeError("blind judge returned an incomplete or mismatched batch")
            judged.extend(decisions)
    for row in judged:
        choice = str(row["choice"])
        row["winner"] = "tie" if choice == "TIE" else "jev" if choice == secret[str(row["posting_id"])] else "terra"
    return {
        "model": JUDGE_MODEL, "rows": judged,
        "jev_wins": sum(row["winner"] == "jev" for row in judged),
        "terra_wins": sum(row["winner"] == "terra" for row in judged),
        "ties": sum(row["winner"] == "tie" for row in judged),
    }


def terra_benchmark(connection, postings: Sequence[Posting], profile_snapshot: dict[str, object]) -> dict[str, Any]:
    sample = random.Random(SAMPLE_SEED).sample(list(postings), min(25, len(postings)))
    rows: list[dict[str, Any]] = []
    for posting in sample:
        started = time.monotonic()
        diagnostics: list[str] = []
        result = core.score_posting(
            profile_snapshot,
            {"id": posting.id, "title": posting.title, "company": posting.company,
             "location": posting.location, "raw_jd": posting.raw_jd},
            [],
            diagnostic=diagnostics.append,
            brain_runner=lambda request, snapshot: run_brain(
                request, snapshot,
                env={"BRAIN": "codex", "CODEX_MODEL": "gpt-5.6-terra", "CODEX_REASONING_EFFORT": "xhigh"},
                timeout_seconds=120,
            ),
        )
        rows.append({"posting_id": posting.id, "completed": result is not None,
                     "diagnostic": diagnostics[-1] if diagnostics else None,
                     "wall_seconds": time.monotonic() - started})
    return {
        "sample_size": len(sample), "completed": sum(row["completed"] for row in rows),
        "wall_seconds": sum(row["wall_seconds"] for row in rows),
        "usage_observable": False, "cost_per_row": None, "rows": rows,
        "note": "The current pipeline exposes no subscription usage telemetry; no cost was inferred.",
    }


def _append_jsonl(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(row) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.run_dir.exists():
        raise RuntimeError("fresh --run-dir required")
    args.run_dir.mkdir(parents=True, mode=0o700)
    with psycopg.connect(args.database_url, autocommit=False) as connection:
        connection.execute("set transaction read only")
        postings = load_scored_postings(connection)
        profile_snapshot = load_profile_snapshot(connection)
        professional_profile = projection.profile_contract(profile_snapshot)
        gold, excluded = load_gold(args.source_c, args.source_d)
        joined, unjoined = join_gold(gold, postings)
        calls_by_id = {posting.id: 1 for posting in postings}
        for row in joined:
            calls_by_id[row.posting.id] = calls_by_id.get(row.posting.id, 0) + RUNS
        estimate = planned_cost(postings, professional_profile, calls_by_id)
        planned_calls = sum(calls_by_id.values())
        print(canonical_json({
            "event": "preflight", "planned_calls": planned_calls,
            "estimated_cost_usd_conservative": estimate, "reserve_usd": args.max_usd,
            "gold": len(gold), "joined": len(joined), "scored_postings": len(postings),
        }), flush=True)
        if estimate > args.max_usd:
            raise RuntimeError("planned conservative cost exceeds reserve")

        configure_tls_ca_bundle()
        client = _load_path_module("jrc_e6_shared_jev", SHARED_JEV)
        previous_cap = os.environ.get("JEV_DAILY_USD_CAP")
        previous_site = os.environ.get("JEV_SITE_JRC_E6_RETROSPECTIVE")
        os.environ["JEV_DAILY_USD_CAP"] = str(args.max_usd)
        os.environ["JEV_SITE_JRC_E6_RETROSPECTIVE"] = "shadow"
        observations: list[dict[str, Any]] = []
        try:
            # Stratum D: one decision for every stored scored posting.
            for posting in postings:
                scored = score_jev(client, posting, professional_profile, args.run_dir / "jev-state", args.timeout_seconds)
                row = {
                    "stratum": "D", "run": 1, "posting_id": posting.id,
                    "public_posting": projection.public_posting({
                        "id": posting.id, "title": posting.title, "company": posting.company,
                        "location": posting.location, "raw_jd": posting.raw_jd,
                    }),
                    "terra_prediction": _terra_choice(posting.score_payload),
                    **scored,
                }
                row["jev_prediction"] = _prediction(row["answer"], row["confidence"], FIXED_FLOOR)
                _append_jsonl(args.run_dir / "observations.jsonl", row)
                observations.append(row)
            # Stratum A/B/C: three independent reruns; never pooled for intervals.
            for run_number in range(1, RUNS + 1):
                for item in joined:
                    scored = score_jev(client, item.posting, professional_profile, args.run_dir / "jev-state", args.timeout_seconds)
                    row = {
                        "stratum": "A", "run": run_number, "posting_id": item.posting.id,
                        "gold": item.verdict.label, "gate": item.verdict.gate,
                        "radar_scraped": item.verdict.radar_scraped,
                        "company": item.verdict.company, "role": item.verdict.role,
                        **scored,
                    }
                    _append_jsonl(args.run_dir / "observations.jsonl", row)
                    observations.append(row)
        finally:
            if previous_cap is None:
                os.environ.pop("JEV_DAILY_USD_CAP", None)
            else:
                os.environ["JEV_DAILY_USD_CAP"] = previous_cap
            if previous_site is None:
                os.environ.pop("JEV_SITE_JRC_E6_RETROSPECTIVE", None)
            else:
                os.environ["JEV_SITE_JRC_E6_RETROSPECTIVE"] = previous_site

        d_rows = [row for row in observations if row["stratum"] == "D"]
        blind, divergence_population = sample_divergences(d_rows)
        (args.run_dir / "blind-sample.json").write_text(json.dumps(blind, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        adjudication = blind_adjudicate(blind, professional_profile)
        (args.run_dir / "blind-adjudication.json").write_text(
            json.dumps(adjudication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        a_rows = [row for row in observations if row["stratum"] == "A"]
        per_run = []
        for run_number in range(1, RUNS + 1):
            current = [row for row in a_rows if row["run"] == run_number]
            per_run.append({
                "run": run_number,
                "overall": gold_metrics(current, FIXED_FLOOR),
                "radar_scraped": gold_metrics([row for row in current if row["radar_scraped"]], FIXED_FLOOR),
                "never_scraped": gold_metrics([row for row in current if not row["radar_scraped"]], FIXED_FLOOR),
                "gate": gold_metrics([row for row in current if row["gate"]], FIXED_FLOOR),
                "non_gate": gold_metrics([row for row in current if not row["gate"]], FIXED_FLOOR),
            })
        recalls = [row["overall"]["recall"] for row in per_run]
        false_rates = [row["overall"]["false_pursue_rate"] for row in per_run]
        summary = {
            "contract": {
                "gold_independence": "Etan final verdicts only; no Terra or Jev field defines or filters gold.",
                "divergence_frame": "Uniform random sample over every D row where the fixed-floor Jev decision differs from Terra, including Jev abstentions.",
                "intervals": "Wilson intervals are per run; no three-run pooling.",
                "stratum_c_gate_source": (
                    "E6-truths-from-etan.md section 7 (superseding sections 1 and 6): Staff, "
                    "Head-of, Principal, Lead, any single requirement over six years, Java, C++, "
                    "C#/.NET, Angular, Python-primary, hard degree, and AI-written essays. Kubernetes "
                    "is a gate only at expert/deep-production level; Orca remains a positive exception."
                ),
                "gate_derived_labels": "Excluded from fit accuracy; Stratum C only partitions Etan-authored verdict rows.",
            },
            "source": {"gold_count": len(gold), "excluded_count": len(excluded)},
            "join": {
                "joined": len(joined), "unjoined": len(unjoined),
                "rate": len(joined) / len(gold) if gold else 0.0,
                "rows": [{**asdict(row.verdict), "posting_id": row.posting.id, "join_method": row.join_method} for row in joined],
                "unjoined_rows": [asdict(row) for row in unjoined],
            },
            "calls": {
                "planned": planned_calls, "actual": len(observations),
                "estimated_cost_usd_conservative": estimate,
                "actual_cost_usd": sum(row["cost_usd"] for row in observations),
                "input_tokens": sum(row["input_tokens"] for row in observations),
                "wall_seconds": sum(row["wall_seconds"] for row in observations),
                "models": sorted({row["model"] for row in observations}),
            },
            "terra": {
                "overall": terra_metrics(joined),
                "radar_scraped": terra_metrics([row for row in joined if row.verdict.radar_scraped]),
                "never_scraped": terra_metrics([row for row in joined if not row.verdict.radar_scraped]),
                "gate": terra_metrics([row for row in joined if row.verdict.gate]),
                "non_gate": terra_metrics([row for row in joined if not row.verdict.gate]),
            },
            "terra_models": {model: sum(row.model == model for row in postings) for model in sorted({row.model for row in postings})},
            "per_run": per_run,
            "variance": {
                "recall_mean": statistics.mean(recalls), "recall_population_stdev": statistics.pstdev(recalls),
                "false_pursue_mean": statistics.mean(false_rates), "false_pursue_population_stdev": statistics.pstdev(false_rates),
            },
            "threshold_curve": [
                {"run": run_number, "floor": floor, **gold_metrics(
                    [row for row in a_rows if row["run"] == run_number], floor
                )}
                for run_number in range(1, RUNS + 1) for floor in FLOORS
            ],
            "stratum_d": {
                "n": len(d_rows),
                "agreement": sum(row["jev_prediction"] == row["terra_prediction"] for row in d_rows) / len(d_rows),
                "divergence_population": divergence_population,
                "blind_sample_size": len(blind), "blind_sample_seed": SAMPLE_SEED,
                "blind_sample_includes_abstentions": any(
                    row["option_a"] == "abstain" or row["option_b"] == "abstain" for row in blind
                ),
                "adjudication": adjudication,
            },
        }
        summary["terra_benchmark"] = terra_benchmark(connection, postings, profile_snapshot)
        (args.run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=DATABASE_URL)
    parser.add_argument("--source-c", type=Path, default=SOURCE_C)
    parser.add_argument("--source-d", type=Path, default=SOURCE_D)
    parser.add_argument("--max-usd", type=float, default=RESERVE_USD)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if not 0 < args.max_usd <= RESERVE_USD:
        raise RuntimeError("--max-usd must be positive and no greater than $0.50")
    summary = run(args)
    print(canonical_json({"summary": str(args.run_dir / "summary.json"), "calls": summary["calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
