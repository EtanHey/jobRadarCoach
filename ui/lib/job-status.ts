import { JobStatusSchema } from "./contracts";
export type JobStatus = typeof JobStatusSchema.options[number];
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

/** "New for me" keeps a visit's cards on screen; one whose status moved on from new shows it as a settled cue. */
export function keptCardStatus(filter: string, status: JobStatus): JobStatus | null {
  return filter === "new-for-me" && status !== "new" ? status : null;
}
