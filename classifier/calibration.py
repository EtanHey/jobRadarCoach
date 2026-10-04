"""Optional, profile-driven scorer calibration over extracted posting requirements."""

from __future__ import annotations

import re
from collections.abc import Mapping


POLICY_FIELDS = {
    "familiar_primary_languages", "conditional_primary_languages",
    "unfamiliar_technologies", "years_conditional",
    "years_hard_block_from", "backend_heavy_max_score",
    "backend_years_no_from", "frontend_parity", "neutral_nice_to_have",
}
OPTIONAL_POLICY_FIELDS = {"target_role_families"}
ROLE_FAMILIES = {"frontend", "fullstack", "product", "backend", "data", "ml", "analytics"}
FACT_FIELDS = {
    "required_years", "required_backend_years", "role_focus",
    "required_technologies", "required_primary_language_clauses",
}
_LANGUAGE_OPTION_SEPARATOR = re.compile(r"\s*(?:/|,|\||\bor\b)\s*", re.IGNORECASE)
_LANGUAGE_ALIASES = {
    "ts": "typescript",
    "typescript": "typescript",
    "js": "javascript",
    "javascript": "javascript",
    "py": "python",
    "python": "python",
    "python3": "python",
    "golang": "go",
    "go": "go",
    "c#": "c#",
    "csharp": "c#",
    "node": "node.js",
    "node.js": "node.js",
    "nodejs": "node.js",
}
_NON_LANGUAGE_RUNTIMES = {"node.js"}
_TECHNOLOGY_ALIASES = {
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "aws": "aws",
    "amazonwebservices": "aws",
    "gcp": "gcp",
    "googlecloudplatform": "gcp",
    "azure": "azure",
    "microsoftazure": "azure",
    "postgres": "postgresql",
    "postgresql": "postgresql",
}


def _names(value: object) -> list[str]:
    if (not isinstance(value, list) or len(value) > 30
            or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in value)
            or len({x.casefold() for x in value}) != len(value)):
        raise ValueError("calibration names must be a bounded unique string list")
    return value


def _language_name(value: str) -> str:
    normalized = " ".join(value.casefold().split()).strip(" .,:;")
    compact = normalized.replace(" ", "")
    return _LANGUAGE_ALIASES.get(compact, normalized)


def _technology_name(value: str) -> str:
    normalized = " ".join(value.casefold().split()).strip(" .,:;")
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    return _TECHNOLOGY_ALIASES.get(compact, normalized)


def _language_options(clause: list[str]) -> set[str]:
    options = {
        _language_name(option)
        for value in clause
        for option in _LANGUAGE_OPTION_SEPARATOR.split(value)
        if option.strip()
    }
    return options - _NON_LANGUAGE_RUNTIMES


def _language_policy(policy: Mapping[str, object]) -> tuple[set[str], dict[str, set[str]]]:
    familiar = {
        _language_name(name)
        for name in policy["familiar_primary_languages"]
    }
    if familiar & {"typescript", "javascript"}:
        familiar.update({"typescript", "javascript"})

    conditional: dict[str, set[str]] = {}
    for name, alternatives in policy["conditional_primary_languages"].items():
        normalized_name = _language_name(name)
        normalized_alternatives = {_language_name(item) for item in alternatives}
        if normalized_name in {"typescript", "javascript"}:
            normalized_names = {"typescript", "javascript"}
        else:
            normalized_names = {normalized_name}
        if normalized_alternatives & {"typescript", "javascript"}:
            normalized_alternatives.update({"typescript", "javascript"})
        for normalized in normalized_names:
            conditional.setdefault(normalized, set()).update(normalized_alternatives)
    return familiar, conditional


def _language_clause_is_familiar(
    options: set[str], familiar: set[str], conditional: Mapping[str, set[str]]
) -> bool:
    return bool(options & familiar) or any(
        name in options and bool(alternatives & options)
        for name, alternatives in conditional.items()
    )


def _required_unfamiliar_count(
    policy: Mapping[str, object], facts: Mapping[str, object]
) -> int:
    required = {
        ("name", _technology_name(name))
        for name in facts["required_technologies"]
    }
    familiar, conditional = _language_policy(policy)
    for clause in facts["required_primary_language_clauses"]:
        options = _language_options(clause)
        if not options or _language_clause_is_familiar(options, familiar, conditional):
            continue
        # A language clause is one OR requirement, even when it names several
        # alternatives. Count it once; a runtime-only clause is ignored above.
        if any(("name", option) in required for option in options):
            continue
        if len(options) == 1:
            required.add(("name", next(iter(options))))
        else:
            required.add(("language_clause", tuple(sorted(options))))
    return len(required)


def _validate_policy_fields(value: object) -> dict[str, object]:
    if (not isinstance(value, dict) or not POLICY_FIELDS <= set(value)
            or set(value) - POLICY_FIELDS - OPTIONAL_POLICY_FIELDS):
        raise ValueError("scorer calibration has unsupported fields")
    if "target_role_families" in value:
        families = _names(value["target_role_families"])
        if not families or not set(families) <= ROLE_FAMILIES:
            raise ValueError("invalid target role families")
    return value


def validate_policy(value: object) -> dict[str, object]:
    value = _validate_policy_fields(value)
    for key in ("familiar_primary_languages", "unfamiliar_technologies", "neutral_nice_to_have"):
        _names(value[key])
    conditional = value["conditional_primary_languages"]
    if not isinstance(conditional, dict) or len(conditional) > 30:
        raise ValueError("invalid conditional primary languages")
    for name, alternatives in conditional.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("invalid conditional language")
        if not _names(alternatives):
            raise ValueError("conditional language needs an alternative")
    for key in ("years_conditional", "years_hard_block_from", "backend_years_no_from"):
        if type(value[key]) is not int or not 0 <= value[key] <= 50:
            raise ValueError(f"invalid calibration {key}")
    if not value["years_conditional"] < value["years_hard_block_from"]:
        raise ValueError("calibration year thresholds must increase")
    if type(value["backend_heavy_max_score"]) is not int or not 40 <= value["backend_heavy_max_score"] <= 59:
        raise ValueError("invalid backend cap")
    if type(value["frontend_parity"]) is not bool:
        raise ValueError("invalid frontend parity")
    return value


def facts_schema(policy: Mapping[str, object]) -> dict[str, object]:
    tech = policy["unfamiliar_technologies"]
    return {
        "type": "object", "additionalProperties": False,
        "required": sorted(FACT_FIELDS),
        "properties": {
            "required_years": {"type": ["integer", "null"], "minimum": 0, "maximum": 50},
            "required_backend_years": {"type": ["integer", "null"], "minimum": 0, "maximum": 50},
            "role_focus": {"type": "string", "enum": ["frontend", "fullstack", "backend", "other", "unknown"]},
            "required_technologies": {"type": "array",
                                      "items": {"type": "string", "enum": tech}},
            "required_primary_language_clauses": {"type": "array", "items": {
                "type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
            }},
        },
    }


def validate_facts(value: object, policy: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != FACT_FIELDS:
        raise ValueError("calibration facts have unsupported fields")
    for key in ("required_years", "required_backend_years"):
        number = value[key]
        if number is not None and (type(number) is not int or not 0 <= number <= 50):
            raise ValueError("invalid required years")
    if value["role_focus"] not in {"frontend", "fullstack", "backend", "other", "unknown"}:
        raise ValueError("invalid role focus")
    tech = _names(value["required_technologies"])
    if not {x.casefold() for x in tech} <= {x.casefold() for x in policy["unfamiliar_technologies"]}:
        raise ValueError("unrecognized required technology")
    clauses = value["required_primary_language_clauses"]
    if not isinstance(clauses, list) or len(clauses) > 10:
        raise ValueError("invalid language clauses")
    for clause in clauses:
        if not _names(clause):
            raise ValueError("empty primary language clause")
    return value


def title_role_family(title: str) -> str | None:
    """Recognize explicit role phrases; generic software/domain titles abstain."""
    title = " ".join(re.sub(r"[-–—]", " ", title.casefold()).split())
    # Specialty phrases win over Product Engineer (e.g. Data Product Engineer).
    if re.search(r"\bdata (?:product |platform |science )?(?:engineer|scientist|developer)\b", title):
        return "data"
    if re.search(r"\b(?:machine learning|ml) (?:software )?(?:engineer|scientist|developer)\b", title):
        return "ml"
    if re.search(r"\b(?:analytics|business intelligence) (?:engineer|developer)\b", title):
        return "analytics"
    frontend = bool(re.search(r"\bfront\s?end\b", title))
    backend = bool(re.search(r"\bback\s?end\b", title))
    if re.search(r"\bfull\s?stack\b", title) or frontend and backend:
        return "fullstack"
    if frontend:
        return "frontend"
    if backend:
        return "backend"
    if re.search(r"\bproduct (?:engineer|developer)\b", title):
        return "product"
    return None


def _title_role_mismatch(policy: Mapping[str, object], title: str) -> bool:
    targets = policy.get("target_role_families")
    if targets is None:
        return False
    family = title_role_family(title)
    return family is not None and family not in targets


def apply_caps(annotation: dict[str, object], policy: Mapping[str, object],
               facts: Mapping[str, object], *,
               title: str = "") -> tuple[dict[str, object], tuple[str, ...]]:
    unfamiliar_count = _required_unfamiliar_count(policy, facts)
    score = annotation["fit_score"]
    rules: list[str] = []
    if _title_role_mismatch(policy, title):
        score = min(score, 59)
        rules.append("title_role_mismatch")
    years = facts["required_years"]
    if years is not None and years >= policy["years_hard_block_from"]:
        score = min(score, 39)
        rules.append("years_hard_block")
    elif years is not None and years >= policy["years_conditional"]:
        score = min(score, 39 if unfamiliar_count else 59)
        rules.append("years_conditional_unfamiliar" if unfamiliar_count else "years_conditional")
    elif unfamiliar_count >= 2:
        score = min(score, 59)
        rules.append("required_unfamiliar")
    if facts["role_focus"] == "backend":
        if (facts["required_backend_years"] is not None
                and facts["required_backend_years"] >= policy["backend_years_no_from"]):
            score = min(score, 39)
            rules.append("backend_years")
        else:
            score = min(score, policy["backend_heavy_max_score"])
            rules.append("backend_heavy")
    if score != annotation["fit_score"]:
        annotation = dict(annotation)
        annotation["fit_score"] = score
        annotation["fit_tier"] = ("strong" if score >= 80 else "good" if score >= 60
                                  else "stretch" if score >= 40 else "weak")
        annotation["recommendation"] = "apply" if score >= 60 else "review" if score >= 40 else "skip"
        if score < 40 and not annotation["fit_line"].startswith("Weak fit —"):
            annotation["fit_line"] = "Weak fit — " + annotation["fit_line"][:148]
    return annotation, tuple(rules)
