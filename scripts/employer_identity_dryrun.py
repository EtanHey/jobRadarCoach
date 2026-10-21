"""Read a frozen JSONL snapshot and report attribution; never connects to a DB."""
import argparse
import hashlib
import json
from pathlib import Path

from scraper.employer_identity import resolve_employer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    groups = {key: [] for key in ('resolved', 'unknown', 'unchanged')}
    for row in map(json.loads, args.snapshot.read_text().splitlines()):
        identity = resolve_employer(row['company'], row['raw_jd'] or '', row['source'])
        employer = identity['hiring_employer']
        key = 'unknown' if employer is None else 'unchanged' if employer.casefold() == row['company'].casefold() else 'resolved'
        groups[key].append((row['id'], identity))
    lines = ['# P7 employer dry run', '', 'STATUS: READ ONLY; no DB writes or backfill applied.', '',
             f'Snapshot SHA256: `{hashlib.sha256(args.snapshot.read_bytes()).hexdigest()}`', '',
             'Storage: additive `posting_extractions.facts.employer_identity`, after strict LLM payload validation. Publisher stays in `postings.company`. No migration or prompt change.', '',
             'Counts are disjoint: resolved means a named employer different from the publisher; unchanged means affirmative source/JD evidence identifies the publisher itself; unknown means neither. Unknown non-agency publishers are not classified as direct.', '']
    for key, rows in groups.items():
        lines += [f'## {key}: {len(rows)}', '', '| ID | Publisher | Hiring employer | Evidence |', '|---|---|---|---|']
        samples = list({(item[1]['publisher'], item[1]['hiring_employer']): item for item in rows}.values())[:10]
        samples += [item for item in rows if item not in samples][:10 - len(samples)]
        for posting_id, identity in samples:
            evidence = (identity['employer_evidence'] or 'No explicit evidence').replace('\n', ' ').replace('|', '\\|')
            lines.append(f"| {posting_id} | {identity['publisher']} | {identity['hiring_employer'] or 'unknown'} | {evidence} |")
        lines.append('')
    lines += ['## Rollout limits', '', 'Stored identities appear on newly extracted postings. The existing selection query skips postings with an extraction receipt; existing rows need a separate authorized deterministic backfill or explicit re-extraction. This slice modifies no existing rows. Legacy known publishers show client undisclosed until evidence is persisted. Unknown legacy non-agency names retain their existing display; that is not a direct-employer assertion. No grouping, scorer employer_type, or LLM prompt changes. New resolver metadata does not replace the model fingerprint.', '']
    args.report.write_text('\n'.join(lines))
    print({key: len(rows) for key, rows in groups.items()})


if __name__ == '__main__':
    main()
