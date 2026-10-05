"""A successful SQL command is not necessarily a successful pgTAP contract."""

import pytest

from test_support.tap import assert_tap


def test_complete_tap_passes():
    assert_tap(["1..2", "ok 1 - table exists", "ok 2 - permission checked"])


@pytest.mark.parametrize(
    "lines",
    [
        [],
        ["ok 1 - missing plan"],
        ["1..2", "ok 1 - truncated result sets"],
        ["1..1", "not ok 1 - permission opened\n# failed assertion"],
        ["1..2", "ok 1", "ok 1 - duplicated result set"],
        ["1..1", "ok 1 # SKIP missing extension"],
        ["1..1", "not ok 1 # TODO fix later"],
        ["1..0"],
        ["1..1", "ok 1", "Bail out! incomplete contract"],
    ],
)
def test_incomplete_or_failed_tap_fails(lines):
    with pytest.raises(AssertionError):
        assert_tap(lines)
