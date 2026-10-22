"""Offline P8E replay; inputs are local evidence files, never a database.

python -m scripts.replay_own_office --plan PATH --snapshot PATH --out PATH
The decision dump lacks full JDs: its replay uses each saved reason's excerpt.
The frozen snapshot and retained probes use their original complete inputs.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import types

from scraper import eligibility

PROFILE = {"candidate": {"location": "Central Israel", "open_to": {
    "geographies": ["Central Israel", "Remote"], "relocation": False,
}}}


def baseline_at(ref):
    module = types.ModuleType("eligibility_replay_baseline")
    sys.modules[module.__name__] = module
    source = subprocess.check_output(["git", "show", f"{ref}:scraper/eligibility.py"], text=True)
    exec(compile(source, f"{ref}:scraper/eligibility.py", "exec"), module.__dict__)
    return module


def replay(row, baseline):
    args = (row, row.get("posting_extractions"), PROFILE)
    return dict(id=row.get("id"), company=row.get("company"), location=row.get("location"),
                before=baseline.decide_location_eligibility(*args),
                after=eligibility.decide_location_eligibility(*args))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", default="e47ee73")
    args = parser.parse_args()
    baseline = baseline_at(args.baseline)
    args.out.mkdir(parents=True, exist_ok=True)
    dump = []
    for row in json.loads((args.plan / "elig-all.json").read_text()):
        quote = re.fullmatch(r'[^:]+: "(.*)"', row["reason"], re.S)
        assert quote, row["id"]
        item = replay(dict(row, raw_jd=quote[1]), baseline)
        item.update(recorded=row["decision"], recorded_reason=row["reason"])
        dump.append(item)
    snapshot = [replay(row, baseline) for row in map(
        json.loads, args.snapshot.read_text().splitlines())]
    probes = []
    # Include every retained round, deduplicating repeated original inputs.
    seen = set()
    for path in sorted(args.plan.glob("P8*-receipts/*.json")):
        if path.parent.resolve() == args.out.resolve():
            continue
        if "probe" not in path.name and "replay" not in path.name:
            continue
        payload = json.loads(path.read_text())
        groups = payload.values() if isinstance(payload, dict) else [payload]
        for group in groups:
            if not isinstance(group, list):
                continue
            for case in group:
                if not isinstance(case, dict) or not isinstance(case.get("jd"), str):
                    continue
                location = case.get("location", "Tel Aviv")
                key = (location, case["jd"])
                if key in seen:
                    continue
                seen.add(key)
                result = replay(dict(id=case.get("id", case.get("case_id")),
                                     location=location, raw_jd=case["jd"]), baseline)
                result.update(source=str(path.relative_to(args.plan)), jd=case["jd"])
                probes.append(result)
    for name, rows in [("dump", dump), ("snapshot", snapshot), ("probes", probes)]:
        (args.out / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    moves = lambda rows: [r for r in rows if r["before"]["eligibility"] != r["after"]["eligibility"]]
    totals = lambda rows, key: dict(Counter(r[key]["eligibility"] for r in rows))
    # This broad cohort includes composite fields with Israeli alternatives;
    # the strict parser must still leave those unresolved.
    israeli = [r for r in dump if re.search(
        r"israel|tel[ -]?aviv|herzliya|ramat[ -]?gan|ra'?anana|haifa|yokneam|jerusalem|gush dan|rishon|netanya|"
        r"kfar saba|petah tikva|rehovot|holon|תל אביב|ירושלים|חיפה",
        r["location"] or "", re.I)]
    cohort = [r for r in israeli if r["recorded"] == "unknown"]
    assert len(cohort) == 401
    summary = dict(
        baseline=args.baseline,
        snapshot_sha256=hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        dump_rows=len(dump), dump_limit="saved reason excerpts, not full JDs",
        dump_recorded=dict(Counter(r["recorded"] for r in dump)),
        israeli_rows=len(israeli), israeli_recorded=dict(Counter(r["recorded"] for r in israeli)),
        unknown_cohort=len(cohort), cohort_baseline=totals(cohort, "before"),
        cohort_after=totals(cohort, "after"),
        cohort_after_reasons=dict(Counter(r["after"]["eligibility_reason"].split(":", 1)[0] for r in cohort)),
        prior_scope_changes=[r for r in cohort if r["recorded_reason"].startswith("Israel/remote")
                             and not r["after"]["eligibility_reason"].startswith("Israel/remote")],
        excerpt_baseline_disagreements=[r for r in cohort
                                       if r["recorded"] != r["before"]["eligibility"]],
        cohort_moves=[r for r in cohort if r["recorded"] != r["after"]["eligibility"]],
        snapshot_rows=len(snapshot), snapshot_before=totals(snapshot, "before"),
        snapshot_after=totals(snapshot, "after"), snapshot_moves=moves(snapshot),
        retained_probes=len(probes), probe_moves=moves(probes),
        new_blocked=[r for r in dump+snapshot+probes if r["before"]["eligibility"] != "blocked"
                     and r["after"]["eligibility"] == "blocked"],
        new_eligible=[r for r in probes if r["before"]["eligibility"] != "eligible"
                      and r["after"]["eligibility"] == "eligible"],
    )
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: len(v) if isinstance(v, list) else v for k,v in summary.items()}, indent=2))
    assert len(snapshot) == 658
    assert summary["snapshot_sha256"] == "520151e36a5a639705a4e56f727ab6ea522ea57bf4490c92a2f4ac8f11a94297"
    assert not summary["new_blocked"]
    assert not summary["prior_scope_changes"]


if __name__ == "__main__":
    main()
