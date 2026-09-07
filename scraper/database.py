"""Atomic first-run profile seeding and DB-owned search snapshots."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Protocol, cast

try:
    from scraper.annotate import _load_safe_profile_contract
except ModuleNotFoundError:  # Direct /app/scraper/harvest.py entrypoint.
    from annotate import _load_safe_profile_contract

PROFILE_SEED_LOCK = 0x4A4F425241444152
UNKNOWN_TEXT_VALUES = frozenset(
    {"unknown", "unspecified", "not specified", "n/a", "na", "none", "null"}
)
REQUIRED_PROFILE_FIELDS = frozenset(
    {
        "contract_version",
        "candidate.positioning",
        "candidate.tenure_years",
        "candidate.location",
        "candidate.fit_terms",
        "candidate.roles_wanted",
        "candidate.stacks",
        "candidate.seniority",
        "candidate.remote",
        "candidate.open_to.geographies",
        "candidate.open_to.work_modes",
        "candidate.open_to.relocation",
        "candidate.preferences.product_company",
        "candidate.preferences.experience_gap",
        "candidate.salary_floor",
        "candidate.red_flag_words",
        "candidate.preferences.free_text",
        "candidate.professional_depth",
        "fit_signals",
        "constraints.global_never_claims",
        "constraints.evidence_scoped_prohibitions",
        "search.terms",
        "search.recency",
        "search.location_terms",
        "runtime.brain",
    }
)


class Result(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...
    def transaction(self) -> AbstractContextManager[object]: ...


def _read_profile(connection: Connection) -> dict[str, object]:
    rows = connection.execute("select field, value from public.profile").fetchall()
    return {str(field): value for field, value in rows}


def _reject_example_placeholders(candidate: dict[str, object]) -> None:
    location = candidate["location"]
    open_to = cast(dict[str, object], candidate["open_to"])
    geographies = cast(list[object], open_to["geographies"])
    values = [location, *geographies]
    if any(isinstance(value, str) and "example city" in value.casefold() for value in values):
        raise ValueError("profile.example.yaml placeholders must be replaced before seeding")


def _seed_loaders():
    main = sys.modules.get("__main__")
    if main is not None and all(
        hasattr(main, name) for name in ("load_profile_contract", "load_searches")
    ):
        return main.load_profile_contract, main.load_searches
    from scraper.harvest import load_profile_contract, load_searches

    return load_profile_contract, load_searches


def build_profile_seed(profile_path: Path, searches_path: Path) -> dict[str, object]:
    """Validate source files and produce every supported profile field."""

    load_profile_contract, load_searches = _seed_loaders()
    projection = _load_safe_profile_contract(profile_path)
    legacy = load_profile_contract(profile_path)
    candidate = projection["candidate"]
    if not isinstance(candidate, dict):
        raise ValueError("candidate profile must be an object")
    if (
        legacy["contract_version"] != 1
        or legacy["positioning"] != candidate["positioning"]
        or set(legacy["fit_terms"]) != set(candidate["fit_terms"])
    ):
        raise ValueError("profile contract and safe projection disagree")
    _reject_example_placeholders(candidate)

    searches = load_searches(searches_path)
    terms = list(dict.fromkeys(search["keywords"] for search in searches))
    recencies = {search["recency"] for search in searches}
    if len(recencies) != 1:
        raise ValueError("all first-run searches must use one recency")
    open_to = cast(dict[str, object], candidate["open_to"])
    preferences = cast(dict[str, object], candidate["preferences"])
    constraints = cast(dict[str, object], projection["constraints"])
    return {
        "contract_version": 1,
        "candidate.positioning": candidate["positioning"],
        "candidate.tenure_years": candidate["tenure_years"],
        "candidate.location": candidate["location"],
        "candidate.fit_terms": candidate["fit_terms"],
        "candidate.roles_wanted": terms,
        "candidate.stacks": [],
        "candidate.seniority": [],
        "candidate.remote": None,
        "candidate.open_to.geographies": open_to["geographies"],
        "candidate.open_to.work_modes": open_to["work_modes"],
        "candidate.open_to.relocation": open_to["relocation"],
        "candidate.preferences.product_company": preferences["product_company"],
        "candidate.preferences.experience_gap": preferences["experience_gap"],
        "candidate.salary_floor": None,
        "candidate.red_flag_words": [],
        "candidate.preferences.free_text": None,
        "candidate.professional_depth": {},
        "fit_signals": projection["fit_signals"],
        "constraints.global_never_claims": constraints["global_never_claims"],
        "constraints.evidence_scoped_prohibitions": constraints["evidence_scoped_prohibitions"],
        "search.terms": terms,
        "search.recency": recencies.pop(),
        "search.location_terms": {},
        "runtime.brain": "ollama",
    }


def load_or_seed_profile(
    connection: Connection, profile_path: Path, searches_path: Path
) -> dict[str, object]:
    """Return one DB snapshot, atomically filling only absent first-run fields."""

    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (PROFILE_SEED_LOCK,))
        current = _read_profile(connection)
        if REQUIRED_PROFILE_FIELDS <= current.keys():
            return current
        seed = build_profile_seed(profile_path, searches_path)
        if set(seed) != REQUIRED_PROFILE_FIELDS:
            raise RuntimeError("profile seed does not cover the required field contract")
        for field, value in seed.items():
            valid = connection.execute(
                "select public.profile_value_is_valid(%s, %s::jsonb)",
                (field, json.dumps(value, ensure_ascii=False)),
            ).fetchone()
            if valid != (True,):
                raise ValueError(f"database rejected seeded profile field: {field}")
            connection.execute(
                "insert into public.profile (field, value) values (%s, %s::jsonb) "
                "on conflict (field) do nothing",
                (field, json.dumps(value, ensure_ascii=False)),
            )
        snapshot = _read_profile(connection)
        if not REQUIRED_PROFILE_FIELDS <= snapshot.keys():
            raise RuntimeError("profile seed did not complete")
        return snapshot


def searches_from_profile(profile: dict[str, object]) -> list[dict[str, str]]:
    """Build operational searches from one already-consistent DB snapshot."""

    terms = profile.get("search.terms")
    geographies = profile.get("candidate.open_to.geographies")
    recency = profile.get("search.recency")
    if not isinstance(terms, list) or not terms or not isinstance(geographies, list) or not geographies:
        raise ValueError("DB profile requires non-empty search terms and geographies")
    if not isinstance(recency, str) or not recency.strip():
        raise ValueError("DB profile requires a search recency")
    return [
        {"keywords": term, "location": geography, "recency": recency}
        for term in terms
        for geography in geographies
        if isinstance(term, str) and isinstance(geography, str)
    ]


def annotation_profile(profile: dict[str, object]) -> dict[str, object]:
    """Rebuild the full local validation contract from one DB snapshot."""

    depth = profile["candidate.professional_depth"]
    candidate = {
        "positioning": profile["candidate.positioning"],
        "tenure_years": profile["candidate.tenure_years"],
        "location": profile["candidate.location"],
        "fit_terms": profile["candidate.fit_terms"],
        "open_to": {
            "geographies": profile["candidate.open_to.geographies"],
            "work_modes": profile["candidate.open_to.work_modes"],
            "relocation": profile["candidate.open_to.relocation"],
        },
        "preferences": {
            "product_company": profile["candidate.preferences.product_company"],
            "experience_gap": profile["candidate.preferences.experience_gap"],
        },
    }
    if depth:
        candidate["professional_depth"] = depth
    return {
        "projection_version": profile["contract_version"],
        "candidate": candidate,
        "fit_signals": profile["fit_signals"],
        "constraints": {
            "global_never_claims": profile["constraints.global_never_claims"],
            "evidence_scoped_prohibitions": profile[
                "constraints.evidence_scoped_prohibitions"
            ],
        },
    }


def _nonblank(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_text(value: object, field: str) -> str:
    text = _nonblank(value)
    if text is None:
        raise ValueError(f"posting {field} must be a nonblank string")
    return text


def _known_text(value: object) -> str | None:
    text = _nonblank(value)
    if text is None or text.casefold() in UNKNOWN_TEXT_VALUES:
        return None
    return text


def _timestamp(value: object) -> datetime | None:
    text = _nonblank(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _known_stack(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        return []
    stack = [_known_text(item) for item in value]
    if any(item is None for item in stack):
        return []
    return list(dict.fromkeys(cast(list[str], stack)))


def _liveness_evidence(posting: dict[str, object]) -> dict[str, object]:
    alive = posting.get("alive")
    status = posting.get("liveness_status")
    reason = _known_text(posting.get("liveness_reason"))
    final_url = _nonblank(posting.get("liveness_final_url"))
    checked_at = _nonblank(posting.get("liveness_checked_at"))
    if (
        not isinstance(alive, bool)
        or type(status) is not int
        or not 100 <= status <= 599
        or reason is None
        or final_url is None
        or _timestamp(checked_at) is None
    ):
        return {}
    return {
        "alive": alive,
        "liveness_status": status,
        "liveness_reason": reason,
        "liveness_final_url": final_url,
        "liveness_checked_at": checked_at,
    }


def _posting_values(posting: dict[str, object], observed_at: datetime) -> tuple[object, ...]:
    source = _required_text(
        posting["source"] if "source" in posting else "linkedin", "source"
    )
    external_id = _required_text(posting.get("id"), "id")
    url = _required_text(posting.get("url"), "url")
    title = _required_text(posting.get("title"), "title")
    company = _required_text(posting.get("company"), "company")
    location = _nonblank(posting.get("location"))
    explicit_remote = posting.get("remote")
    remote = explicit_remote if isinstance(explicit_remote, bool) else None
    if remote is None and location and re.search(r"\bremote\b", location, re.I):
        remote = True
    apply_url = _nonblank(posting.get("apply_url"))
    return (
        source, external_id, url, title, company,
        location, remote, _known_text(posting.get("seniority")),
        _known_stack(posting.get("stack")),
        _nonblank(posting.get("salary")), apply_url or url,
        _timestamp(posting.get("posted_at")), _nonblank(posting.get("jd_text")),
        observed_at, observed_at,
        json.dumps(_liveness_evidence(posting), ensure_ascii=False),
        apply_url is not None,
    )


POSTING_UPSERT = """
insert into public.postings as current (
  source, external_id, url, title, company, location, remote, seniority, stack,
  salary, apply_url, posted_at, raw_jd, first_seen_at, last_seen_at, liveness
) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
on conflict on constraint postings_source_external_id_key do update set
  url = excluded.url, title = excluded.title, company = excluded.company,
  location = coalesce(excluded.location, current.location),
  apply_url = case
    when %s then excluded.apply_url
    else coalesce(current.apply_url, excluded.apply_url)
  end,
  remote = coalesce(excluded.remote, current.remote),
  seniority = coalesce(excluded.seniority, current.seniority),
  stack = case when cardinality(excluded.stack) > 0 then excluded.stack else current.stack end,
  salary = coalesce(excluded.salary, current.salary),
  posted_at = coalesce(excluded.posted_at, current.posted_at),
  raw_jd = coalesce(excluded.raw_jd, current.raw_jd),
  last_seen_at = greatest(excluded.last_seen_at, current.last_seen_at),
  liveness = case
    when excluded.liveness <> '{}'::jsonb and case
      when pg_input_is_valid(current.liveness->>'liveness_checked_at', 'timestamptz')
      then (excluded.liveness->>'liveness_checked_at')::timestamptz >=
           (current.liveness->>'liveness_checked_at')::timestamptz
      else true
    end then excluded.liveness
    else current.liveness
  end
returning id
"""


def persist_postings(
    connection: Connection, postings: list[dict[str, object]], observed_at: str
) -> list[str]:
    """Atomically upsert observations and initialize only missing statuses."""

    timestamp = _timestamp(observed_at)
    if timestamp is None:
        raise ValueError("harvested_at must be an offset-aware ISO timestamp")
    posting_ids: list[str] = []
    with connection.transaction():
        for posting in postings:
            row = connection.execute(POSTING_UPSERT, _posting_values(posting, timestamp)).fetchone()
            if row is None:
                raise RuntimeError("posting upsert returned no durable identity")
            posting_id = str(row[0])
            posting_ids.append(posting_id)
            connection.execute(
                "insert into public.posting_status (posting_id) values (%s) "
                "on conflict (posting_id) do nothing",
                (posting_id,),
            )
    return posting_ids
