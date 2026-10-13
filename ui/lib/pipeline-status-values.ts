// Shared leaf module avoids a contracts ↔ job-status import cycle.
export const pipelineStatusValues = [
  "worth_checking", "applied", "screen", "interview_technical", "interview_final",
  "offer", "contract", "rejected", "archived", "not_relevant",
] as const;
