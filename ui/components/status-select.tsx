"use client";
import { useState } from "react";
import type { JobDetail, StatusPatch } from "@/lib/contracts";
import { statusLabels, statusOptions, type JobStatus, type StatusChangeResult } from "@/lib/job-status";
import { AppSelect } from "./ui/select";
import { Button } from "./ui/button";

export function StatusSelect({job, saving, changeStatus}: {job: JobDetail; saving: boolean; changeStatus: (patch: StatusPatch) => Promise<StatusChangeResult>}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  // Pessimistic: the select keeps the server's value while saving, and a failure is reported right under it.
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function save(patch: StatusPatch) {
    setPending(true); setError("");
    const result = await changeStatus(patch);
    setPending(false);
    if (!result.ok && result.error) setError(result.error);
    return result.ok;
  }
  function choose(value: string) {
    if (value === "rejected") { setReason(job.status === "rejected" ? job.status_reason ?? "" : ""); setRejecting(true); }
    else { setRejecting(false); void save({status: value as Exclude<JobStatus, "rejected" | "skipped">}); }
  }
  return <fieldset disabled={saving} className="min-w-0"><AppSelect label="Application status" value={job.status} options={statusOptions} onValueChange={choose} busy={pending} />
    {pending && <p role="status" className="sr-only">Saving status…</p>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">Status not saved, still {statusLabels[job.status]}. {error}</p>}
    {job.status === "rejected" && !rejecting && <button type="button" className="mt-2 text-xs underline" onClick={() => choose("rejected")}>Edit rejection reason</button>}
    {rejecting && <form className="mt-3 grid gap-2" onSubmit={async (event) => { event.preventDefault(); if (reason.trim()) { if (await save({status:"rejected",reason})) setRejecting(false); } }}>
      <label htmlFor="pipeline-rejection" className="text-xs">Why did the company reject the application?</label><textarea id="pipeline-rejection" required maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} className="rounded-lg border bg-background p-2 text-sm" />
      <div className="flex gap-2"><Button type="submit" disabled={!reason.trim()}>Confirm rejection</Button><Button type="button" variant="ghost" onClick={()=>setRejecting(false)}>Cancel</Button></div>
    </form>}
  </fieldset>;
}
