# Scraper

Credential-free harvesting for LinkedIn guest search and public Comeet, Greenhouse, Lever, and Workable boards. Harvesting uses no login, cookies, browser profile, stored credentials, or metered API key.

## Profile

Copy `profile.example.yaml` to the gitignored `profile.yaml` and replace every example value with your own. The image deliberately does not contain either file; mount `profile.yaml` read-only at runtime.

The container runs as the image's `radar` user (UID/GID 1000). On Linux, a restrictive profile such as mode `0600` must therefore be owned by UID/GID 1000 before it is bind-mounted; for example, `chmod 0600 profile.yaml && sudo chown 1000:1000 profile.yaml`. macOS Docker Desktop and OrbStack remap host mounts, so ownership behavior there is runtime-specific. If you override the container with `--user`, also use a host directory owned by that user for `/app/data` instead of the Docker-managed volume shown below.

`searches.yaml` is a transitional Israel-regional example with generic public role names. The inherited ATS filter currently requires that regional setting; changing only the locations can silently eliminate ATS matches. Lane 2 must replace both search selection and posting-location filtering with DB/profile-driven geography before this is stranger-ready.

## Local run

```bash
python3 scraper/harvest.py --profile profile.yaml --output-dir data/job-feed --max-pages 1
```

Enable reviewed public ATS sources with `--sources comeet,greenhouse,lever,workable`. Luna annotation is best-effort and uses `codex exec` when that binary is available; deterministic JSONL output remains available when it is not.

The subscription runner is verified against `codex-cli 0.153.4` and fails closed
on any other version. It gives Codex an empty temporary home containing only a
symlink to the existing subscription credential, runs from a separate data-only
temporary directory, ignores user configuration and rules, disables local and
MCP-capable tool surfaces, and passes only an allowlisted environment. Strict
configuration makes an unsupported isolation flag a nonzero runner failure; it
does not fall back to ordinary Codex read-only mode, which is not a privacy
boundary.

## Docker

Build from the repository root:

```bash
docker build -t job-radar:dev -f scraper/Dockerfile .
docker volume create job-radar-data
docker run --rm \
  -v "$PWD/profile.yaml:/app/profile.yaml:ro" \
  -v "job-radar-data:/app/data" \
  job-radar:dev --profile /app/profile.yaml --max-pages 1 --jd-fetch-cap 3
```

No profile is copied into the image. The only persistent output is the Docker-managed `job-radar-data` volume mounted at `/app/data`.

## Tests

```bash
python3 -m pytest scraper -q
```
