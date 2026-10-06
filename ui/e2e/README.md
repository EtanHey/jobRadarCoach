# e2e pilot

Run from `ui/` with Node >=22.12 and `npm ci`. Browser/app data is synthetic;
no `.env` is loaded. Chromium uses headless shell, one worker, no retries or
video. App startup copies `prepare-globe-fixture.mjs` output, removes API
routes, and binds an allocated loopback port. Never deploy the copied app.

Locally, run exactly one suite through the fleet cap:

```sh
JRC_E2E_ARGS='--repeat-each 5' /Users/etanheyman/Gits/jobRadarCoach/docs.local/tools/run-suite-capped.sh e2e/run-capped.mjs 3072 600
/Users/etanheyman/Gits/jobRadarCoach/docs.local/tools/run-suite-capped.sh e2e/compare.mjs 3072 600
```

CI uses `npm run test:e2e`: `cap.sh` is the portable equivalent, with the
same 3072 MB aggregate process-tree RSS ceiling, 600 s deadline, 2 s sampling,
and PID-only termination. It reports peak RSS and elapsed time. Install only
headless shell with `npx playwright install chromium --only-shell --with-deps`.
Telemetry is disabled for both e2e and Next. CI never configures a model.

All four flows are strict deterministic gates against the landed chain. Each flow also has a hybrid variant with
`agent.act` and `agent.assert`; these skip before acquiring the agent unless
`JRC_E2E_MODEL_CONFIG` names an explicitly configured local module. The runner
passes only a small environment allowlist, excluding paid API keys.

To enable subscription steps locally, install `ai` and the provider required
by your subscription, run `E2E_TELEMETRY_DISABLED=1 npx e2e login openai`, then
create an ignored `.e2e/model.mts` exporting the agent configuration:

```ts
import { chatgpt } from 'e2e/oauth/chatgpt';
export default { model: chatgpt('YOUR_SUBSCRIPTION_MODEL'), maxSteps: 12, maxModelCalls: 12 };
```

Set `JRC_E2E_MODEL_CONFIG` to its absolute path. For a local server, export an
AI SDK model instance using your installed local provider instead. Do not
commit model configuration or credentials. CI ignores the module even if set.

Run uncached with `JRC_E2E_ARGS='--no-cache --repeat-each 5'`; run again without
`--no-cache` for cached observations. Read `.e2e/results/report.json` for model
usage and each step's cache result. `act` records only after a later locator
assertion verifies its result; `assert` always calls the model. Our focus and
network checks remain deterministic. The local cache is ignored, never shared.

Mutation runs use `JRC_E2E_MUTATION=drawer|status|delayed|pill|hidden` plus a matching
`--grep` selection without spaces (e.g. `--grep status.*deterministic`);
`JRC_E2E_ARGS` uses whitespace splitting, not shell quote parsing. Changes apply only to the disposable app. Every subsequent
run recreates it from source, restoring the mutation. Unknown/nonmatching
mutations abort startup, which is an infrastructure failure, not test RED.

Docs read: [Quickstart](https://e2e.tester.army/docs/quickstart),
[Goals/assertions/locators](https://e2e.tester.army/docs/core-concepts),
[Starting the app](https://e2e.tester.army/docs/web),
[Cache](https://e2e.tester.army/docs/cache), [Models](https://e2e.tester.army/docs/models),
[Security](https://e2e.tester.army/docs/security),
[Telemetry](https://e2e.tester.army/docs/telemetry), [CI](https://e2e.tester.army/docs/ci).

Status and hidden-pill negative checks use a deliberate 3000 ms quiet window,
covering the current 800 ms prefetch timer and the reviewed 1500 ms delayed
refresh mutation. Status counters are rechecked at test end. This is bounded
coverage, not proof against arbitrary future timers or the 90 s poll.

`compare.mts` is a same-harness direct-Playwright baseline, not an independent
implementation or a run of existing browser-tests. Existing `status-select.mjs`,
`new-roles-pill.mjs`, and `date-icons.mjs` cover broader scenarios and are retained;
their runtime was not remeasured here.

Review r1 CI run 37457216872 peaked at 2492 MB against the 3072 MB cap
(81.1% used, 580 MB headroom). The existing cap is retained; a cap exit 137
is a resource failure, not an assertion failure.
