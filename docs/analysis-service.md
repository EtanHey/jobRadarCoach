# Production analysis service

The private extraction and scoring worker is a persistent production dependency of the hosted Job Radar dashboard. It is installed as the `jobradarcoach-analysis` Python distribution and scheduled by the per-user macOS LaunchAgent `com.jobradarcoach.local-analysis`. `launchd` is the service manager; the repository does not add a parallel daemon manager.

## Immutable installation

Build the wheel from the exact reviewed source commit. The thin installer creates or reuses the dedicated virtual environment, installs the wheel and its declared dependencies, and atomically prepares the plist and manifest. It does not call `launchctl`.

For the first installation only, compile the reviewed native helper to a staged non-symlink path and install it at the stable identity used by its Keychain access control:

```sh
install -d -m 700 "$HOME/.local/share/jobRadarCoach/bin"
/usr/bin/xcrun swiftc -O scripts/local_analysis_credentials.swift \
  -o /ABSOLUTE/STAGING/jobradarcoach-analysis-credentials
install -m 755 /ABSOLUTE/STAGING/jobradarcoach-analysis-credentials \
  "$HOME/.local/share/jobRadarCoach/bin/jobradarcoach-analysis-credentials"
```

If that stable binary already exists, do not recompile or replace it during a Python wheel upgrade. Compare its source and binary hashes with the existing manifest. A change requires an explicit helper reprovisioning procedure.

```sh
git rev-parse HEAD
python3 -m build --wheel
python3 -m scripts.install_analysis_service \
  --wheel /ABSOLUTE/dist/jobradarcoach_analysis-0.1.0-py3-none-any.whl \
  --venv /ABSOLUTE/VENV \
  --database-url-file /ABSOLUTE/PRIVATE/passwordless-database-url \
  --codex /ABSOLUTE/codex-0.153.4/bin/codex \
  --credential-helper-source "$PWD/scripts/local_analysis_credentials.swift" \
  --credential-helper "$HOME/.local/share/jobRadarCoach/bin/jobradarcoach-analysis-credentials" \
  --dashboard-origin https://REPLACE-WITH-PRODUCTION-HOST \
  --source-commit REPLACE_WITH_FULL_REVIEWED_GIT_SHA \
  --plist-template "$PWD/docs/com.jobradarcoach.local-analysis.plist.example" \
  --manifest-template "$PWD/docs/analysis-service-manifest.example.json" \
  --state-dir "$HOME/Library/Application Support/jobRadarCoach/local-analysis" \
  --launch-agents-dir "$HOME/Library/LaunchAgents"
/ABSOLUTE/VENV/bin/python -m pip check
/ABSOLUTE/VENV/bin/jrc-analysis-worker --help
```

The reviewed native credential helper must already exist at its stable path before this command runs. The installer records SHA-256 hashes for the wheel, helper Swift source, and helper binary. On later wheel upgrades it preserves the helper binary and fails closed if either helper hash changed, because replacing that executable can invalidate its Keychain access control and requires deliberate reprovisioning. The wheel hash distinguishes reviewed builds even while the distribution version remains `0.1.0`.

Initial credential provisioning is a separate root-owned ceremony. It passes the exact approved database password through standard input to `jobradarcoach-analysis-credentials provision`; it never places the password in arguments, the plist, or the manifest.

The database URL reference file contains exactly one passwordless PostgreSQL URI and has owner-only permissions. The installer places that non-secret URI directly in the generated plist so the helper can inherit it, but does not put the URI in the manifest or command line. The helper supplies only `PGPASSWORD`; recurring execution has no `op` fallback.

The install resolves the wheel's declared, pinned dependencies into the same virtual environment. Re-running the command updates that installation and replaces the prepared plist and manifest under the same production identity. Keep reference files outside the checkout with owner-only permissions. The manifest contains paths and identifiers only; never put credential values in it.

The installer creates the state and log directories and prepares `~/Library/LaunchAgents/com.jobradarcoach.local-analysis.plist`. Validate the resulting owner-only paths and plist before loading it:

```sh
chmod 700 "$HOME/Library/Application Support/jobRadarCoach/local-analysis" \
  "$HOME/Library/Application Support/jobRadarCoach/local-analysis/logs"
plutil -lint "$HOME/Library/LaunchAgents/com.jobradarcoach.local-analysis.plist"
```

Loading or restarting the LaunchAgent is a release action owned by the root operator. A source merge or wheel build does not activate or replace the running production service.

If `maintenance.json` exists in the state directory, installation and plist preparation must preserve it. Root clears that marker only after the replacement service completes a real verified cycle.

## Native launchd operations

Use `launchctl` against the logged-in user's GUI domain. These commands expose native service state without a custom wrapper:

```sh
launchctl print "gui/$(id -u)/com.jobradarcoach.local-analysis"
cat "$HOME/Library/Application Support/jobRadarCoach/local-analysis/status.json"
tail -n 100 "$HOME/Library/Application Support/jobRadarCoach/local-analysis/logs/"*.jsonl
tail -n 100 "$HOME/Library/Application Support/jobRadarCoach/local-analysis/logs/"*.log
```

Initial loading uses the reviewed plist copied into `~/Library/LaunchAgents`:

```sh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.jobradarcoach.local-analysis.plist"
```

Stopping production is always deliberate and explicit:

```sh
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.jobradarcoach.local-analysis.plist"
```

Do not delete the plist, manifest, maintenance marker, state directory, or dated logs as part of a stop. For repair or upgrade, preserve those records, install the reviewed artifact in place, validate the manifest and plist, then bootstrap the same label. Do not create a second overlapping daemon or rename the existing production label during repair.

Packaging gives the worker a stable installed identity; it does not by itself prove unattended Keychain access or a successful production analysis cycle.

## Standards references

- [PyPA entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/)
- [Apple guide to creating launchd jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
