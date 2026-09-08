# Mac setup

This runs Job Radar Coach on one Mac: OrbStack k3s hosts the jobs and UI, local Supabase stores data, and native Ollama provides the default batch model. The UI has no login. Expose it only with Tailscale Serve, never Funnel or a public route.

## 1. Install the host tools

Install Command Line Tools and [Homebrew](https://brew.sh), then install the runtime tools:

```zsh
xcode-select -p >/dev/null 2>&1 || xcode-select --install
brew install --cask orbstack tailscale-app
brew install node python supabase/tap/supabase ollama
```

Launch OrbStack, enable Kubernetes in its settings, and sign in to the Tailscale app. In Tailscale settings, install the **CLI integration** ([official CLI setup](https://tailscale.com/docs/reference/tailscale-cli?tab=macos)), then open a new terminal. The app installation alone does not make the `tailscale` command available. Then verify the local cluster and CLI:

```zsh
open -a OrbStack
orbctl start
kubectl config use-context orbstack
kubectl wait --for=condition=Ready nodes --all --timeout=120s
open -a Tailscale
command -v tailscale && tailscale status
```

## 2. Clone and protect the checkout

Clone the public repository:

```zsh
git clone https://github.com/EtanHey/jobRadarCoach.git
cd jobRadarCoach
git config core.hooksPath .githooks
python3 scripts/check_private_files.py --all-tracked
```

The hook and audit command reject private files before they enter a commit. Do not bypass them.

## 3. Create the private profile

Copy the public shape, keep the private copy ignored, and edit every example value into truthful evidence:

```zsh
cp profile.example.yaml profile.yaml
chmod 600 profile.yaml
${EDITOR:-vi} profile.yaml
git check-ignore -q profile.yaml
python3 - <<'PY'
from pathlib import Path
from scraper.database import REQUIRED_PROFILE_FIELDS, build_profile_seed

seed = build_profile_seed(Path("profile.yaml"), Path("scraper/searches.yaml"))
assert set(seed) == REQUIRED_PROFILE_FIELDS
print("profile seed is valid")
PY
```

Keep `safe_radar_projection` as the final indented JSON block. Its positioning and fit terms must match the legacy `profile` section. Replace all `Example City` values, example claims, evidence identifiers, scopes, and exclusions. Keep at least one truthful verified fit signal and one global never-claim. `scraper/searches.yaml` supplies the initial role terms and recency; the private profile supplies geographies.

The first scraper transaction validates and inserts the complete profile seed. After that, the database is runtime truth; editing `profile.yaml` does not overwrite existing rows.

## 4. Start storage and the default brain

Apply pending migrations without resetting or deleting an existing database:

```zsh
supabase start
supabase migration up --local
brew services start ollama
ollama pull qwen2.5:7b-instruct
```

Ollama runs on the Mac. Model jobs reach it at `http://host.docker.internal:11434`. Strict schema and evidence checks may reject a model answer: a nonzero `failed` count is a failure receipt, not proof that a result row was stored.

## 5. Build the local images

One public Python image contains all three batch stages. Give its single build all three names expected by the manifests. Build the UI from the allowlisted `ui` context:

```zsh
docker build -f scraper/Dockerfile \
  -t job-radar:dev \
  -t job-radar-extractor:dev \
  -t job-radar-classifier:dev .
docker build -f ui/Dockerfile -t job-radar-ui:dev ui
```

The images stay local; the manifests use `imagePullPolicy: Never`.

## 6. Create runtime-only Kubernetes Secrets

Use an unused tailnet HTTPS port. These commands use `8445` and preserve existing handlers on `443` or `8443`; if `8445` is occupied, choose another port and replace it throughout this guide, including the origin validation. The following Python reads Supabase status on file descriptor 3, replaces only a parsed loopback hostname, preserves URL-encoded database user information, and pipes Secret JSON directly to `kubectl`. It does not put credentials in command arguments, files, or terminal output.

```zsh
set -euo pipefail
tailscale serve status --json | python3 -c 'import json,sys; assert "8445" not in json.load(sys.stdin).get("TCP", {}), "HTTPS port 8445 is already configured"'
kubectl apply -f k8s/namespace.yaml
runtime_tailnet_host="$(
  tailscale status --json | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
)"
runtime_ui_origin="https://${runtime_tailnet_host}:8445"

UI_ORIGIN="${runtime_ui_origin}" \
python3 - 3< <(supabase status -o json) <<'PY' | kubectl apply -f -
import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit

status = json.load(os.fdopen(3))

def required(name):
    value = status.get(name)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"supabase status omitted {name}")
    return value

def pod_url(name, schemes):
    parsed = urlsplit(required(name))
    if parsed.scheme not in schemes or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit(f"unexpected local {name} URL")
    userinfo, separator, _ = parsed.netloc.rpartition("@")
    netloc = f"{userinfo}@" if separator else ""
    netloc += "host.docker.internal"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

origin = urlsplit(os.environ["UI_ORIGIN"])
try:
    origin_port = origin.port
except ValueError:
    raise SystemExit("UI_ORIGIN has an invalid port") from None
if (
    origin.scheme != "https" or not origin.hostname or origin_port != 8445
    or origin.username is not None or origin.password is not None
    or origin.path not in {"", "/"} or origin.query or origin.fragment
):
    raise SystemExit("UI_ORIGIN must be a full HTTPS origin on port 8445")
livekit_host = f"[{origin.hostname}]" if ":" in origin.hostname else origin.hostname
livekit_public_url = urlunsplit(("wss", f"{livekit_host}:8446", "", "", ""))

def secret(name, values):
    return {
        "apiVersion": "v1", "kind": "Secret", "type": "Opaque",
        "metadata": {"name": name, "namespace": "job-radar-coach"},
        "stringData": values,
    }

document = {
    "apiVersion": "v1", "kind": "List", "items": [
        secret("supabase-db", {
            "DATABASE_URL": pod_url("DB_URL", {"postgres", "postgresql"}),
        }),
        secret("ui-runtime", {
            "SUPABASE_URL": pod_url("API_URL", {"http", "https"}),
            "SUPABASE_SERVICE_ROLE_KEY": required("SERVICE_ROLE_KEY"),
            "UI_ORIGIN": os.environ["UI_ORIGIN"],
            "LIVEKIT_PUBLIC_URL": livekit_public_url,
        }),
    ],
}
json.dump(document, sys.stdout, separators=(",", ":"))
PY

kubectl -n job-radar-coach create secret generic scraper-profile \
  --from-file=profile.yaml=profile.yaml \
  --dry-run=client -o json | kubectl apply -f -
unset runtime_tailnet_host runtime_ui_origin
```

The service-role key remains server-side. Never commit Secret output, `profile.yaml`, `.env` files, Supabase credentials, or Codex authentication.

## 7. Deploy and run one bounded batch

Apply the suspended scraper template and UI. Do not apply the extractor or classifier Job manifests directly; the coordinator reads them with client dry-run and creates uniquely named jobs.

```zsh
kubectl apply -f k8s/scraper-cronjob.yaml
kubectl apply -f k8s/ui.yaml
kubectl -n job-radar-coach rollout status deployment/ui --timeout=120s
python3 scripts/run_batch.py --limit 1 --timeout-seconds 120
```

The scraper CronJob must remain suspended. The coordinator prints one receipt covering fetched, matched, new, extracted, and scored counts. An empty observed cohort safely skips both model jobs.
Every generated Job keeps its Job and pod available for logs for one hour after completion, then Kubernetes removes them through `ttlSecondsAfterFinished: 3600`. Keep that TTL on any new or ad-hoc validation Job so completed resources do not accumulate.

### Optional Codex batch brain

The Python image contains the supported Codex CLI. Mount only an existing subscription authentication file at runtime, then select Codex explicitly for that run:

```zsh
runtime_codex_auth="${CODEX_HOME:-${HOME}/.codex}/auth.json"
test -s "${runtime_codex_auth}"
kubectl -n job-radar-coach create secret generic batch-codex-auth \
  --from-file=auth.json="${runtime_codex_auth}" \
  --dry-run=client -o json | kubectl apply -f -
unset runtime_codex_auth
python3 scripts/run_batch.py --limit 1 --timeout-seconds 120 \
  --extractor-provider codex --classifier-provider codex
```

The portable default remains Ollama. Only Ollama and Codex are implemented batch providers.

## 8. Serve the UI on the tailnet

Keep this localhost bridge running in its own terminal:

```zsh
kubectl -n job-radar-coach port-forward service/ui 3000:3000
```

Wait for the bridge to print `Forwarding from 127.0.0.1:3000`. If the local port is occupied, use another free port in both bridge commands. In a second terminal, add only the chosen HTTPS handler:

```zsh
tailscale serve --bg --https=8445 http://127.0.0.1:3000
tailscale serve status
```

Open `https://<this-machine-tailnet-name>:8445` from a device on the same tailnet. The exact full origin must match the `UI_ORIGIN` stored above or mutations are rejected. Do not use `tailscale serve reset`: it would remove unrelated handlers.

The foreground port-forward is session-scoped. Restart it after logout, reboot, or a selected UI pod restart. Portable setup does not install a background bridge.

### Prepare the voice transport

These transport steps require an installed LiveKit Deployment and Service with the `livekit-keys`
API Secret configured. Verify their readiness and the tracked bridge source before exposing voice ports:

```zsh
set -euo pipefail
kubectl --context orbstack -n job-radar-coach rollout status deployment/livekit --timeout=120s
python3 - 3< <(kubectl --context orbstack -n job-radar-coach get service/livekit -o json) <<'PY'
import json

service = json.load(open(3))
ports = {
    (item.get("port"), item.get("targetPort"), item.get("protocol", "TCP"))
    for item in service.get("spec", {}).get("ports", [])
}
required = {(7880, 7880, "TCP"), (7881, 7881, "TCP")}
if not required <= ports:
    raise SystemExit("service/livekit must expose numeric TCP 7880->7880 and 7881->7881")
PY
node --check scripts/livekit_bridge.cjs
lsof -nP -iTCP:17880 -sTCP:LISTEN -t || true
lsof -nP -iTCP:17881 -sTCP:LISTEN -t || true
```

If both `lsof` commands have no output, keep `node scripts/livekit_bridge.cjs` running in its own
terminal. If both ports already belong to the same PID, reuse it only when `ps -ww -o command= -p
<PID>` is exactly `node` plus this checkout's `scripts/livekit_bridge.cjs`, and the health checks below
pass. A single occupied port, different PIDs, or any other command is a conflict; do not stop or replace
that process.

Check the existing Serve targets before adding anything. This read-only check prints `missing` or
`reuse` for each voice mapping and exits nonzero on a conflicting handler:

```zsh
runtime_tailnet_host="$(tailscale status --json | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
TAILNET_DNS="${runtime_tailnet_host}" python3 - 3< <(tailscale serve status --json) <<'PY'
import json
import os

status = json.load(open(3))
dns = os.environ["TAILNET_DNS"]
tcp = status.get("TCP", {})
web = status.get("Web", {})

rtc = tcp.get("7881")
if rtc not in (None, {"TCPForward": "127.0.0.1:17881"}):
    raise SystemExit("conflict: TCP 7881 has another target")
print("tcp:7881", "missing" if rtc is None else "reuse")

signaling = tcp.get("8446")
handlers = web.get(f"{dns}:8446", {}).get("Handlers", {})
expected = {"/": {"Proxy": "http://127.0.0.1:17880"}}
if not (signaling is None and not handlers) and not (
    signaling == {"HTTPS": True} and handlers == expected
):
    raise SystemExit("conflict: HTTPS 8446 has another target")
print("https:8446", "missing" if signaling is None else "reuse")
PY
```

If `tcp:7881` printed `missing`, add the media mapping:

```zsh
tailscale serve --bg --tcp=7881 tcp://127.0.0.1:17881
```

If `https:8446` printed `missing`, add the signaling mapping:

```zsh
tailscale serve --bg --https=8446 http://127.0.0.1:17880
```

Leave every `reuse` mapping untouched. Then verify signaling:

```zsh
curl -fsS -o /dev/null http://127.0.0.1:17880/
curl -fsS -o /dev/null "https://${runtime_tailnet_host}:8446/"
unset runtime_tailnet_host
```

Never use `tailscale serve reset` or Funnel. On cleanup, stop the bridge only if this terminal launched
it, using Ctrl-C or SIGTERM for that exact PID. Remove only a mapping that this setup created, after the
same status check still reports its exact target, with `tailscale serve --tcp=7881 off` or `tailscale
serve --https=8446 off`. Keep reused processes and mappings.

## Repeat starts

Do not reset Supabase and do not recreate your profile. Start the services, apply pending migrations, rebuild only changed images, reapply changed manifests, restart the foreground port-forward, and run another bounded batch when wanted.
