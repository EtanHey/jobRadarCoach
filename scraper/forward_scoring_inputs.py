"""Freeze the 30 forward-test labels and professional-only scoring inputs."""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from classifier import projection
from scraper.forward_scoring_harness import canonical_json
from scraper.forward_scoring_policy import parse_verdict


def parse_part1_answers(text: str) -> dict[int, str]:
    answers = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        match = re.match(r"^(\d+)\s+—", cells[0]) if len(cells) >= 2 else None
        if match:
            answers[int(match.group(1))] = cells[1]
    return answers


def parse_part2_answers(text: str) -> dict[str, str]:
    answers, current = {}, None
    for line in text.splitlines():
        if match := re.match(r"^##\s+(P\d+)\.", line):
            current = match.group(1)
        elif current and line.startswith("Verdict:"):
            answers[current] = line.removeprefix("Verdict:").strip()
    return answers


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _plain_html(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", unescape(re.sub(r"<[^>]+>", "\n", value))).strip()


def fetch_part2(mapping: dict[str, Any]) -> dict[str, dict[str, object]]:
    boards, postings = {}, {}
    for row in mapping["postings"]:
        parsed = urlsplit(row["url"])
        parts = [unquote(item) for item in parsed.path.split("/") if item]
        if (
            parsed.scheme != "https"
            or parsed.netloc != "jobs.ashbyhq.com"
            or len(parts) != 2
        ):
            raise ValueError(f"invalid public Ashby locator: {row['p_number']}")
        board, posting_id = parts
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
        matches = [job for job in boards[board] if posting_id in job.get("jobUrl", "")]
        if len(matches) != 1 or not matches[0].get("isListed"):
            raise ValueError(
                f"public Ashby locator is not uniquely live: {row['p_number']}"
            )
        job = matches[0]
        if job.get("title") != row["title"]:
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
) -> None:
    expected[locator] = part
    label = parse_verdict(verdict)
    if label is None:
        dropped.append(
            {"locator": locator, "part": part, "reason": "ambiguous truth verdict"}
        )
        return
    if {"human_verdict", "verdict"} & set(posting):
        raise ValueError("public posting contains a truth-label field")
    frozen = {
        "professional_profile": profile,
        "public_posting": posting,
        "history_policy": "excluded",
    }
    rows.append(
        {
            "part": part,
            "locator": locator,
            "frozen_input": frozen,
            "input_sha256": _sha(frozen),
            "gold": {"verbatim": verdict, "label": label},
            "jev": [],
        }
    )


def assemble_manifest(
    profile: dict[str, object],
    map1: dict[str, Any],
    answers1: dict[int, str],
    postings1: dict[str, dict[str, object]],
    map2: dict[str, Any],
    answers2: dict[str, str],
    postings2: dict[str, dict[str, object]],
) -> dict[str, Any]:
    keys1 = {int(item["heading_number"]) for item in map1["postings"]}
    keys2 = {str(item["p_number"]) for item in map2["postings"]}
    if (
        keys1 != set(answers1)
        or keys2 != set(answers2)
        or len(keys1) + len(keys2) != 30
    ):
        raise ValueError("gold answers must match the exact 20/10 mapped cohort")
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
    return {
        "schema_version": 1,
        "expected_locators": expected,
        "dropped": dropped,
        "rows": rows,
    }


def materialize_manifest(
    *,
    part1_answers: Path,
    part1_mapping: Path,
    part2_answers: Path,
    part2_mapping: Path,
    database_url: str,
) -> dict[str, Any]:
    map1 = json.loads(part1_mapping.read_text(encoding="utf-8"))
    map2 = json.loads(part2_mapping.read_text(encoding="utf-8"))
    answers1 = parse_part1_answers(part1_answers.read_text(encoding="utf-8"))
    answers2 = parse_part2_answers(part2_answers.read_text(encoding="utf-8"))
    profile, postings1 = capture_part1(map1, database_url)
    postings2 = fetch_part2(map2)
    return assemble_manifest(
        profile, map1, answers1, postings1, map2, answers2, postings2
    )
