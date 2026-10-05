"""Conservative location labels; structured source values always win."""

import re
from collections.abc import Mapping

_LABEL = r'(?:hybrid|(?:fully\s+)?remote|on[-\s]?site)'
_SUFFIX = re.compile(
    rf'(?:\(\s*(?P<round>{_LABEL})\s*\)|\[\s*(?P<square>{_LABEL})\s*\]|'
    rf'(?:^|\s+(?:[·|,–—-]\s*)?)(?P<plain>{_LABEL}))\s*$', re.I,
)


def canonical_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r'[-\s]', '', value.lower())
    return {'hybrid': 'hybrid', 'remote': 'remote', 'fullyremote': 'remote',
            'onsite': 'on-site'}.get(normalized)


def location_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _SUFFIX.search(value.strip())
    if not match:
        return None
    # Multiple labels, including a preceding parenthetical label, are ambiguous.
    prefix = value.strip()[:match.start()]
    if any(char in prefix for char in '()[]'):
        return None
    if re.search(rf'\b{_LABEL}\b', prefix, re.I):
        return None
    return canonical_mode(match.group("round") or match.group("square") or match.group("plain"))


def posting_mode(posting: Mapping[str, object]) -> tuple[str | None, str | None]:
    explicit = canonical_mode(posting.get('work_mode'))
    if explicit:
        return explicit, 'structured'
    remote = posting.get('remote')
    if isinstance(remote, bool):
        return ('remote' if remote else 'on-site'), 'structured'
    inferred = location_mode(posting.get('location'))
    return inferred, 'location' if inferred else None
