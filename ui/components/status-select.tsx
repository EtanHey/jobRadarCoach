"use client";
import { useState } from "react";
import type { JobDetail, StatusPatch } from "@/lib/contracts";
import { statusOptions, type JobStatus } from "@/lib/job-status";
import { AppSelect } from "./ui/select";
import { Button } from "./ui/button";

export function StatusSelect({job, saving, changeStatus}: {job: JobDetail; saving: boolean; changeStatus: (patch: StatusPatch) => Promise<boolean>}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  function choose(value: string) {
    if (value === "rejected") { setReason(job.status === "rejected" ? job.status_reason ?? "" : ""); setRejecting(true); }
    else { setRejecting(false); void changeStatus({status: value as Exclude<JobStatus, "rejected">}); }
  }
  return <fieldset disabled={saving} className="min-w-0"><AppSelect label="Application status" value={job.status} options={statusOptions} onValueChange={choose} />
    {job.status === "rejected" && !rejecting && <button type="button" className="mt-2 text-xs underline" onClick={() => choose("rejected")}>Edit rejection reason</button>}
    {rejecting && <form className="mt-3 grid gap-2" onSubmit={async (event) => { event.preventDefault(); if (reason.trim()) { if (await changeStatus({status:"rejected",reason})) setRejecting(false); } }}>
      <label htmlFor="pipeline-rejection" className="text-xs">Why did the company reject the application?</label><textarea id="pipeline-rejection" required maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} className="rounded-lg border bg-background p-2 text-sm" />
      <div className="flex gap-2"><Button type="submit" disabled={!reason.trim()}>Confirm rejection</Button><Button type="button" variant="ghost" onClick={()=>setRejecting(false)}>Cancel</Button></div>
    </form>}
  </fieldset>;
}
