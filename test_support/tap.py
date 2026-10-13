"""Validate all pgTAP result sets, including plans and skipped assertions."""

import re
from collections.abc import Iterable


def assert_tap(results: Iterable[str]) -> None:
    lines = [line for result in results for line in result.splitlines()]
    output = "\n".join(lines)
    assert not any(
        re.match(r"(?:not ok\b|Bail out!)", line)
        or re.search(r"#\s*(?:SKIP|TODO)\b", line, re.IGNORECASE)
        for line in lines
    ), output
    plans = [int(match[1]) for line in lines if (match := re.fullmatch(r"1\.\.(\d+)", line))]
    assert len(plans) == 1 and plans[0] > 0, output or "No TAP output"
    numbers = [int(match[1]) for line in lines if (match := re.match(r"ok (\d+)\b", line))]
    assert numbers == list(range(1, plans[0] + 1)), output
