import { JobStatusSchema } from "./contracts";
export type JobStatus = typeof JobStatusSchema.options[number];
export const statusLabels: Record<JobStatus, string> = {
  new: "New", seen: "Seen", worth_checking: "Worth checking", applied: "Applied", screen: "Screen",
  interview_technical: "Technical interview", interview_final: "Final interview", offer: "Offer",
  contract: "Contract", rejected: "Rejected", archived: "Archived", not_relevant: "Not relevant",
};
export const statusOptions = JobStatusSchema.options.map((value) => ({value, label: statusLabels[value]}));
