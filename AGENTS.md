# Repository agent instructions

## Production analysis service ownership

`com.jobradarcoach.local-analysis` is a persistent production dependency of the hosted Job Radar dashboard. Treat its loaded LaunchAgent, dedicated virtual environment, installed wheel, plist, manifest, state directory, and logs as operator-owned production resources.

- Do not stop, unload, kill, delete, rename, or replace this service during blanket cleanup, QA teardown, test cleanup, or worktree cleanup.
- Read-only status and log inspection is allowed. A stop requires an explicit task instruction naming this production service.
- Root owns installation, activation, restart, and release. Source workers may prepare reviewed artifacts but must not mutate the running service.
- Repair the existing `com.jobradarcoach.local-analysis` label in place. Preserve the manifest, maintenance marker, state, and dated logs, and do not create a second overlapping daemon. Root clears maintenance only after a real replacement cycle is verified.
- Keep credentials out of source, manifests, logs, and agent output.

The logged-in macOS account owner can always control their LaunchAgent. These rules prevent accidental automation cleanup; they do not claim the service is impossible to stop.
