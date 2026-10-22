import { z } from "zod";

export const LivenessSchema = z.object({
  state: z.enum(["confirmed", "stale", "closed", "deadline_passed"]),
  last_confirmed_at: z.iso.datetime({ offset: true }).nullable(),
  application_deadline: z.iso.datetime({ offset: true }).nullable(),
});

// Hourly ats-liveness.yml checks every ATS row; allow one skipped run plus scheduling jitter.
export const LIVENESS_FRESH_MS = 3 * 60 * 60 * 1000;
const instant = z.iso.datetime({ offset: true });
function timestamp(value: unknown): string | null {
  return instant.safeParse(value).data ?? null;
}

// JSON keys are projected individually by PostgREST; validate at this boundary.
export function projectLiveness(evidence: {
  alive?: unknown; liveness_checked_at?: unknown; last_attempt_verdict?: unknown; application_deadline?: unknown;
}, now = Date.now()) {
  const checked = timestamp(evidence.liveness_checked_at);
  const deadline = timestamp(evidence.application_deadline);
  const confirmed = evidence.alive === true && checked && Date.parse(checked) <= now ? checked : null;
  let state: z.infer<typeof LivenessSchema>["state"] = "stale";
  if (evidence.alive === false) state = "closed";
  else if (deadline && Date.parse(deadline) < now) state = "deadline_passed";
  else if (confirmed && now - Date.parse(confirmed) <= LIVENESS_FRESH_MS
    && (evidence.last_attempt_verdict == null || evidence.last_attempt_verdict === "alive")) state = "confirmed";
  return {
    alive: state === "confirmed" ? true : state === "closed" || state === "deadline_passed" ? false : null,
    liveness: { state, last_confirmed_at: confirmed, application_deadline: deadline },
  };
}

export function livenessLabel(evidence: z.infer<typeof LivenessSchema>, now = Date.now()): string {
  switch (evidence.state) {
    case "closed": return "Closed";
    case "deadline_passed": return "Application deadline passed";
    case "confirmed":
    case "stale": {
      if (!evidence.last_confirmed_at) return "Availability unconfirmed";
      const hours = Math.max(0, Math.floor((now - Date.parse(evidence.last_confirmed_at)) / 3_600_000));
      const days = Math.floor(hours / 24);
      const age = hours === 0 ? "less than an hour" : days > 0 ? `${days} ${days === 1 ? "day" : "days"}`
        : `${hours} ${hours === 1 ? "hour" : "hours"}`;
      const stale = evidence.state === "stale" || now - Date.parse(evidence.last_confirmed_at) > LIVENESS_FRESH_MS;
      return `Last confirmed ${age} ago${stale ? " · latest availability unconfirmed" : ""}`;
    }
  }
}
