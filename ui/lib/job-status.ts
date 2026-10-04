import { JobStatusSchema, type JobSummary, type StatusPatch } from "./contracts";
export type JobStatus = typeof JobStatusSchema.options[number];
export function isStatusPatchNoop(job: Pick<JobSummary, "status" | "status_reason">, patch: StatusPatch): boolean {
  return patch.status === job.status && (!("reason" in patch) || patch.reason === undefined || patch.reason === job.status_reason);
}
export function statusMutationRemovesCard(filter: string, status: JobStatus): boolean {
  return filter === "new-for-me" && status !== "new";
}
export const pipelineStatusValues = [
  "worth_checking", "applied", "screen", "interview_technical", "interview_final",
  "offer", "contract", "rejected", "archived", "not_relevant",
] as const;
export type PipelineStatus = typeof pipelineStatusValues[number];
export const statusLabels: Record<JobStatus, string> = {
  new: "New", seen: "Seen", worth_checking: "Worth checking", skipped: "Skipped", applied: "Applied", screen: "Screen",
  interview_technical: "Technical interview", interview_final: "Final interview", offer: "Offer",
  contract: "Contract", rejected: "Rejected", archived: "Archived", not_relevant: "Not relevant",
};
export const statusOptions = JobStatusSchema.options.filter((value) => value !== "skipped")
  .map((value) => ({value, label: statusLabels[value]}));
export const pipelineStatusOptions = pipelineStatusValues.map((value) => ({ value, label: statusLabels[value] }));
