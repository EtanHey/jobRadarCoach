"""Freeze the 30 forward-test labels and professional-only scoring inputs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from classifier import projection
from scraper.annotate import provider_payload_projection
from scraper.forward_scoring_harness import canonical_json
from scraper.forward_scoring_policy import parse_verdict


def parse_part1_answers(text: str) -> dict[int, str]:
    answers = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        match = re.match(r"^(\d+)\s+—", cells[0]) if len(cells) >= 2 else None
        if match:
            key = int(match.group(1))
            if key in answers:
                raise ValueError(f"duplicate Part 1 answer heading: {key}")
            answers[key] = cells[1]
    return answers


def parse_part2_answers(text: str) -> dict[str, str]:
    answers, sections, current = {}, set(), None
    for line in text.splitlines():
        if match := re.match(r"^##\s+(P\d+)\.", line):
            current = match.group(1)
            if current in sections:
                raise ValueError(f"duplicate public answer heading: {current}")
            sections.add(current)
        elif current and line.startswith("Verdict:"):
            if current in answers:
                raise ValueError(f"duplicate public verdict: {current}")
            answers[current] = line.removeprefix("Verdict:").strip()
    return answers


def parse_part3_answers(text: str) -> dict[str, dict[str, str]]:
    answers: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        match = re.match(r"^-\s+(P\d+)\b.*?\*\*(.+?)\*\*\s+—\s+(.*)$", line)
        if not match:
            continue
        key, verdict, comment = match.groups()
        if key in answers:
            raise ValueError(f"duplicate Part 3 answer: {key}")
        answers[key] = {"verbatim": verdict, "comment": comment}
    return answers


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _plain_html(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", unescape(re.sub(r"<[^>]+>", "\n", value))).strip()


def _ashby_locator(value: object, *, required: bool = False) -> tuple[str, str] | None:
    parsed = urlsplit(value) if isinstance(value, str) else None
    parts = (
        [unquote(item) for item in parsed.path.split("/") if item]
        if parsed is not None
        else []
    )
    valid = (
        parsed is not None
        and parsed.scheme == "https"
        and parsed.netloc == "jobs.ashbyhq.com"
        and not parsed.query
        and not parsed.fragment
        and len(parts) == 2
        and all(part and "/" not in part for part in parts)
    )
    if not valid:
        if required:
            raise ValueError("invalid public Ashby locator")
        return None
    return parts[0], parts[1]


def fetch_part2(mapping: dict[str, Any]) -> dict[str, dict[str, object]]:
    boards, postings = {}, {}
    for row in mapping["postings"]:
        try:
            board, posting_id = _ashby_locator(row["url"], required=True)
        except ValueError as error:
            raise ValueError(
                f"invalid public Ashby locator: {row['p_number']}"
            ) from error
        if board not in boards:
            url = (
                "https://api.ashbyhq.com/posting-api/job-board/"
                f"{quote(board, safe='')}?includeCompensation=true"
            )
            request = Request(
                url, headers={"User-Agent": "JobRadarCoach-forward-scoring/1"}
            )
            with urlopen(request, timeout=30) as response:
                boards[board] = json.load(response)["jobs"]
        matches = [
            job
            for job in boards[board]
            if job.get("isListed") is True
            and _ashby_locator(job.get("jobUrl")) == (board, posting_id)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"public Ashby locator is not uniquely live: {row['p_number']}"
            )
        job = matches[0]
        if " ".join(job.get("title", "").split()) != " ".join(row["title"].split()):
            raise ValueError(f"public Ashby title changed: {row['p_number']}")
        description = job.get("descriptionPlain") or _plain_html(
            job.get("descriptionHtml", "")
        )
        postings[row["p_number"]] = projection.public_posting(
            {
                "id": f"ashby:{board}:{posting_id}",
                "title": job["title"],
                "company": row["company"],
                "location": job.get("location", ""),
                "raw_jd": description,
            }
        )
    return postings


def capture_part1(
    mapping: dict[str, Any], database_url: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    import psycopg

    postings = {}
    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute("set transaction read only")
        profile = {
            str(field): value
            for field, value in connection.execute(
                "select field, value from public.profile order by field"
            ).fetchall()
        }
        professional_profile = projection.profile_contract(profile)
        for row in mapping["postings"]:
            captured = connection.execute(
                "select id::text, title, company, location, raw_jd "
                "from public.postings where id = %s",
                (row["posting_id"],),
            ).fetchone()
            if captured is None:
                raise LookupError(f"Part 1 posting missing: {row['heading_number']}")
            raw = dict(zip(("id", "title", "company", "location", "raw_jd"), captured))
            postings[str(row["heading_number"])] = projection.public_posting(raw)
        connection.rollback()
    return professional_profile, postings


def _add(
    rows: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    expected: dict[str, int],
    *,
    part: int,
    locator: str,
    profile: dict[str, object],
    posting: dict[str, object],
    verdict: str,
    comment: str | None = None,
) -> None:
    expected[locator] = part
    label = parse_verdict(verdict)
    if label is None:
        dropped.append(
            {
                "locator": locator,
                "part": part,
                "reason": "ambiguous truth verdict",
                "gold": {"verbatim": verdict, "label": None},
            }
        )
        return
    if {"human_verdict", "verdict"} & set(posting):
        raise ValueError("public posting contains a truth-label field")
    hosted_payload = provider_payload_projection(posting, profile)
    frozen = {
        "hosted_payload": hosted_payload,
        "reference_validation_profile": profile,
        "history_policy": "excluded",
    }
    gold = {"verbatim": verdict, "label": label}
    if comment is not None:
        gold["comment"] = comment
    rows.append(
        {
            "part": part,
            "locator": locator,
            "frozen_input": frozen,
            "input_sha256": _sha(frozen),
            "gold": gold,
        }
    )


def _mapping_keys(
    mapping: Mapping[str, Any], field: str, expected: set[object], label: str
) -> list[object]:
    entries = mapping.get("postings")
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError("gold answers must match the exact 20/10/10 mapped cohort")
    keys = [item.get(field) if isinstance(item, Mapping) else None for item in entries]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {label} mapping identifier")
    if set(keys) != expected:
        raise ValueError("gold answers must match the exact 20/10/10 mapped cohort")
    return keys


def _freeze_identity(manifest: Mapping[str, Any]) -> dict[str, object]:
    return {
        "schema_version": manifest["schema_version"],
        "expected_locators": manifest["expected_locators"],
        "dropped": manifest["dropped"],
        "rows": [
            {
                key: row[key]
                for key in ("part", "locator", "frozen_input", "input_sha256", "gold")
            }
            for row in manifest["rows"]
        ],
    }


def verify_freeze_receipt(manifest: Mapping[str, Any]) -> None:
    receipt = manifest.get("freeze_receipt")
    identity = _freeze_identity(manifest)
    expected = {
        "algorithm": "sha256",
        "sha256": _sha(identity),
        "planned_count": len(manifest["expected_locators"]),
        "included_count": len(manifest["rows"]),
        "dropped_count": len(manifest["dropped"]),
    }
    if receipt != expected:
        raise ValueError(
            "freeze receipt does not match truth, cohort, drop, and inputs"
        )


def assemble_manifest(
    profile: dict[str, object],
    map1: dict[str, Any],
    answers1: dict[int, str],
    postings1: dict[str, dict[str, object]],
    map2: dict[str, Any],
    answers2: dict[str, str],
    postings2: dict[str, dict[str, object]],
    map3: dict[str, Any],
    answers3: dict[str, dict[str, str]],
    postings3: dict[str, dict[str, object]],
) -> dict[str, Any]:
    keys1 = _mapping_keys(map1, "heading_number", set(range(1, 21)), "Part 1")
    keys2 = _mapping_keys(
        map2, "p_number", {f"P{index}" for index in range(1, 11)}, "Part 2"
    )
    keys3 = _mapping_keys(
        map3, "p_number", {f"P{index}" for index in range(11, 21)}, "Part 3"
    )
    posting_ids = [item["posting_id"] for item in map1["postings"]]
    if len(posting_ids) != len(set(posting_ids)):
        raise ValueError("duplicate Part 1 posting ID")
    public_entries = [*map2["postings"], *map3["postings"]]
    urls = [item["url"] for item in public_entries]
    locators = [_ashby_locator(url, required=True) for url in urls]
    if len(urls) != len(set(urls)) or len(locators) != len(set(locators)):
        raise ValueError("duplicate public mapping URL or posting ID")
    if (
        set(keys1) != set(answers1)
        or set(keys2) != set(answers2)
        or set(keys3) != set(answers3)
    ):
        raise ValueError("gold answers must match the exact 20/10/10 mapped cohort")
    for keys, postings in (
        ({str(key) for key in keys1}, postings1),
        (set(keys2), postings2),
        (set(keys3), postings3),
    ):
        if set(postings) != keys:
            raise ValueError("captured posting keys do not match the mapped cohort")
    rows, dropped, expected = [], [], {}
    for item in map1["postings"]:
        key = int(item["heading_number"])
        locator = f"part1:{key}:{item['posting_id']}"
        _add(
            rows,
            dropped,
            expected,
            part=1,
            locator=locator,
            profile=profile,
            posting=postings1[str(key)],
            verdict=answers1[key],
        )
    for item in map2["postings"]:
        key = str(item["p_number"])
        locator = f"part2:{key}:{postings2[key]['id']}"
        _add(
            rows,
            dropped,
            expected,
            part=2,
            locator=locator,
            profile=profile,
            posting=postings2[key],
            verdict=answers2[key],
        )
    for item in map3["postings"]:
        key = str(item["p_number"])
        locator = f"part3:{key}:{postings3[key]['id']}"
        truth = answers3[key]
        _add(
            rows,
            dropped,
            expected,
            part=3,
            locator=locator,
            profile=profile,
            posting=postings3[key],
            verdict=truth["verbatim"],
            comment=truth["comment"],
        )
    if len(rows) + len(dropped) != 40 or set(expected) != {
        row["locator"] for row in [*rows, *dropped]
    }:
        raise ValueError("every mapped locator needs one included or dropped outcome")
    manifest = {
        "schema_version": 1,
        "expected_locators": expected,
        "dropped": dropped,
        "rows": rows,
    }
    manifest["freeze_receipt"] = {
        "algorithm": "sha256",
        "sha256": _sha(_freeze_identity(manifest)),
        "planned_count": len(expected),
        "included_count": len(rows),
        "dropped_count": len(dropped),
    }
    for row in rows:
        row["jev"] = []
    verify_freeze_receipt(manifest)
    return manifest


def materialize_manifest(
    *,
    part1_answers: Path,
    part1_mapping: Path,
    part2_answers: Path,
    part2_mapping: Path,
    part3_answers: Path,
    part3_mapping: Path,
    database_url: str,
) -> dict[str, Any]:
    map1 = json.loads(part1_mapping.read_text(encoding="utf-8"))
    map2 = json.loads(part2_mapping.read_text(encoding="utf-8"))
    map3 = json.loads(part3_mapping.read_text(encoding="utf-8"))
    answers1 = parse_part1_answers(part1_answers.read_text(encoding="utf-8"))
    answers2 = parse_part2_answers(part2_answers.read_text(encoding="utf-8"))
    answers3 = parse_part3_answers(part3_answers.read_text(encoding="utf-8"))
    profile, postings1 = capture_part1(map1, database_url)
    public_postings = fetch_part2({"postings": [*map2["postings"], *map3["postings"]]})
    postings2 = {key: public_postings[key] for key in answers2}
    postings3 = {key: public_postings[key] for key in answers3}
    return assemble_manifest(
        profile,
        map1,
        answers1,
        postings1,
        map2,
        answers2,
        postings2,
        map3,
        answers3,
        postings3,
    )
