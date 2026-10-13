import { filterJobGroups, type ViewOptions } from "../../lib/job-filters";
import type { JobSummary } from "../../lib/contracts";
import { titleSeniority } from "../../lib/job-metadata";
async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const { rows, cases } = JSON.parse(input) as { rows: JobSummary[]; cases: ViewOptions[] };
  // The old list enters the TS view newest-found first, with id breaking ties.
  rows.sort((a, b) => b.first_seen_at.localeCompare(a.first_seen_at) || a.id.localeCompare(b.id));
  const summaries = rows.map(row => ({ ...row, seniority: row.seniority ?? titleSeniority(row.title) }));
  process.stdout.write(JSON.stringify(cases.map(options => filterJobGroups(summaries, options).slice(0, 1000).map(group => group.job.id))));
}
void main();
