# Run and crash recovery

Use `jrc run` (or `jrc run --qa`) in the foreground. Ctrl-C cleans up the resources recorded as owned. `jrc down` exists for cleanup after a crashed terminal or supervisor; it is not a required second step in a normal session.

A new run obtains the exclusive supervisor lock, checks that the previous supervisor identity is no longer live, and cleans up its recorded owned resources before starting. Recovery uses the previous run's normal/QA mode even when the new run requests a different mode. It never releases the lock between recovery and startup. Borrowed resources are untouched.

If an identity changed, an adapter is unavailable, or cleanup fails, the new run refuses to start and preserves the remaining ownership records. It does not guess which process to stop. Durable `.run-logs` survive both recovery and ordinary teardown; retained readiness snapshots are diagnostic evidence, not proof of a live agent.
