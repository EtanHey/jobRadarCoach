"""Optional, profile-driven scorer calibration over extracted posting requirements."""

from __future__ import annotations

from collections.abc import Mapping


POLICY_FIELDS = {
    "familiar_primary_languages", "conditional_primary_languages",
    "unfamiliar_technologies", "years_ignore_through", "years_conditional",
    "years_hard_block_from", "backend_heavy_max_score",
    "backend_years_no_from", "frontend_parity", "neutral_nice_to_have",
}
FACT_FIELDS = {
    "required_years", "required_backend_years", "role_focus",
    "required_technologies", "required_primary_language_clauses",
}


def _names(value: object) -> list[str]:
    if (not isinstance(value, list) or len(value) > 30
            or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in value)
            or len({x.casefold() for x in value}) != len(value)):
        raise ValueError("calibration names must be a bounded unique string list")
    return value


def validate_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != POLICY_FIELDS:
        raise ValueError("scorer calibration has unsupported fields")
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
    for key in ("years_ignore_through", "years_conditional", "years_hard_block_from", "backend_years_no_from"):
        if type(value[key]) is not int or not 0 <= value[key] <= 50:
            raise ValueError(f"invalid calibration {key}")
    if not (value["years_ignore_through"] < value["years_conditional"]
            < value["years_hard_block_from"]):
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


def apply_caps(annotation: dict[str, object], policy: Mapping[str, object],
               facts: Mapping[str, object]) -> tuple[dict[str, object], tuple[str, ...]]:
    familiar = {x.casefold() for x in policy["familiar_primary_languages"]}
    conditional = {key.casefold(): {x.casefold() for x in alternatives}
                   for key, alternatives in policy["conditional_primary_languages"].items()}
    unfamiliar = bool(facts["required_technologies"])
    for clause in facts["required_primary_language_clauses"]:
        options = {x.casefold() for x in clause}
        if not (options & familiar or any(
            name in options and alternatives & options for name, alternatives in conditional.items()
        )):
            unfamiliar = True
    score = annotation["fit_score"]
    rules: list[str] = []
    years = facts["required_years"]
    if years is not None and years >= policy["years_hard_block_from"]:
        score = min(score, 39)
        rules.append("years_hard_block")
    elif years is not None and years >= policy["years_conditional"]:
        score = min(score, 39 if unfamiliar else 59)
        rules.append("years_conditional_unfamiliar" if unfamiliar else "years_conditional")
    elif unfamiliar:
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
