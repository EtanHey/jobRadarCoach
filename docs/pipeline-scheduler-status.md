# Pipeline scheduler status receipt

`scripts/pipeline_scheduler_status.py` converts the private full-pipeline attempt and verified receipt files into one compact, read-only JSON object. A failed newest attempt always wins over an older successful receipt, so a stale `latest.json` cannot make the scheduler look healthy.

Run `python3 scripts/pipeline_scheduler_status.py`.

The command also performs bounded, read-only `launchctl` checks. It exits zero for `healthy` and `running`, and exits nonzero for `failed`, `disabled`, `stalled`, `stale`, or `unknown`. A recent successful attempt cannot hide an unloaded or disabled LaunchAgent. It never starts, stops, or enables a scheduler.

The dashboard can expose this through an authenticated, read-only server route and poll it once per minute. Render `state`, `reason`, and `latest_attempt.finished_at`; show the prior verified counts separately under `last_verified`. Do not render private stdout/stderr archives or treat `last_verified` as the current scheduler state.

This helper observes only the legacy local LaunchAgent named `com.jobradarcoach.full-pipeline`. It does not inspect or control the hosted cloud schedule, and the standalone source no longer includes a Kubernetes coordinator or job templates.
