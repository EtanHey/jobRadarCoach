import { JobStatusSchema } from "./contracts";
export type JobStatus = typeof JobStatusSchema.options[number];
export const pipelineStatusValues = [
  "worth_checking", "applied", "screen", "interview_technical", "interview_final",
  "offer", "contract", "rejected", "archived", "not_relevant",
] as const;
export type PipelineStatus = typeof pipelineStatusValues[number];
export const statusLabels: Record<JobStatus, string> = {
  new: "New", seen: "Seen", worth_checking: "Worth checking", applied: "Applied", screen: "Screen",
  interview_technical: "Technical interview", interview_final: "Final interview", offer: "Offer",
  contract: "Contract", rejected: "Rejected", archived: "Archived", not_relevant: "Not relevant",
};
export const statusOptions = JobStatusSchema.options.map((value) => ({value, label: statusLabels[value]}));
export const pipelineStatusOptions = pipelineStatusValues.map((value) => ({ value, label: statusLabels[value] }));
