"""Large boards use controlled exact details, never partial-board absence."""
import json
from datetime import timedelta, timezone
import pytest
from scraper import ats_liveness as ats
from scraper.recheck import recheck
from scraper.test_provider_closure import row, transport
from scraper.test_recheck import Database
from scraper.test_ats_board_adapters import page


def large_board():
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if json.loads(kwargs["data"])["searchText"]:
            return page("workday", [], 0)
        payload = json.loads(page("workday", ["2", "3"], 2000))
        payload["jobPostings"][0]["externalPath"] = "/job/City/Live_R2"
        return json.dumps(payload)
    return ats.BoardChecker(fetch), calls


@pytest.mark.parametrize("target,control,expected", [
    ("live", "live", True), ("gone", "live", False),
    ("error", "live", None), ("mismatch", "live", None),
    ("gone", "gone", None), ("gone", "error", None)])
def test_large_board_exact_detail_requires_valid_sibling(monkeypatch, target, control, expected):
    calls = transport(monkeypatch, "workday", target, control)
    # Reuse the closure transport's authenticated sibling path.
    board, lists = large_board()
    result = board(row("workday"))
    assert result["alive"] is expected
    assert len(lists) == 2
    assert len(calls) == (2 if control == "live" else 1)


def test_large_board_keeps_spaced_closure_gate_and_reopens(monkeypatch):
    class Clock(ats.datetime):
        current = ats.datetime(2026, 10, 11, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None): return cls.current
    monkeypatch.setattr(ats, "datetime", Clock)
    posting = row("workday")
    transport(monkeypatch, "workday")
    state = {"alive": True}
    def run():
        board, _ = large_board()
        db = Database([("id", posting["url"], "workday", posting["external_id"], dict(state))])
        receipt = recheck(db, board_checker=board)
        state.update(json.loads(db.writes[0][1][0]))
        return receipt
    assert run()["closed"] == 0 and state["alive"] is True
    Clock.current += timedelta(minutes=2)
    assert run()["closed"] == 0 and state["alive"] is True
    Clock.current += timedelta(hours=1)
    assert run()["closed"] == 1 and state["alive"] is False
    transport(monkeypatch, "workday", target="live")
    Clock.current += timedelta(hours=1)
    assert run()["alive"] == 1 and state["alive"] is True


def test_large_board_target_cannot_authenticate_its_own_404(monkeypatch):
    calls = transport(monkeypatch, "workday")
    board = ats.BoardChecker(lambda *a, **k: page("workday", ["1"], 2000))
    assert board(row("workday"))["alive"] is None
    assert calls == []


def test_large_board_unknown_detail_breaks_closure_streak(monkeypatch):
    transport(monkeypatch, "workday", target="error")
    board, _ = large_board()
    posting = row("workday")
    posting["liveness"] = {"alive": True, "ats_miss_count": 1,
                          "ats_first_miss_at": "2026-10-01T00:00:00+00:00"}
    result = board(posting)
    update = ats.reliability_update(posting, result, lambda _: pytest.fail("uncertainty cannot close"))
    assert "alive" not in update and update["ats_miss_count"] == 0


def test_large_board_renamed_requisition_remains_alive(monkeypatch):
    calls = transport(monkeypatch, "workday", target="gone")
    def fetch(url, **kwargs):
        search = json.loads(kwargs["data"])["searchText"]
        return page("workday", ["2"], 2000) if not search else json.dumps({
            "total": 1, "jobPostings": [{"title": "New title", "bulletFields": ["R1"],
            "externalPath": "/job/NewCity/New-Title_R1"}]})
    result = ats.BoardChecker(fetch)(row("workday"))
    assert result["alive"] is True and calls == []
    assert result["liveness_reason"] == "workday-targeted-list-present"
