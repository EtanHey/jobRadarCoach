import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JobCard } from "../../components/job-card";
import type { JobSummary } from "../../lib/contracts";

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const rows = JSON.parse(input) as JobSummary[];
  process.stdout.write(JSON.stringify(rows.map(job => renderToStaticMarkup(
    <JobCard job={job} openerRef={{ current: null }} selectJob={() => {}}><span>{job.stack.join(", ")}</span></JobCard>,
  ))));
}
void main();
