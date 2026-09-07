"""Atomic first-run profile seeding and DB-owned search snapshots."""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
from pathlib import Path
from typing import Protocol, cast

from scraper.annotate import _load_safe_profile_contract
from scraper.harvest import load_profile_contract, load_searches

PROFILE_SEED_LOCK = 0x4A4F425241444152
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


def build_profile_seed(profile_path: Path, searches_path: Path) -> dict[str, object]:
    """Validate source files and produce every supported profile field."""

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
