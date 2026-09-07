# Scraper

Credential-free harvesting for LinkedIn guest search and public Comeet, Greenhouse, Lever, and Workable boards. Harvesting uses no login, cookies, browser profile, stored credentials, or metered API key.

## Profile

Copy `profile.example.yaml` to the gitignored `profile.yaml` and replace every example value with your own. The image deliberately does not contain either file; mount `profile.yaml` read-only at runtime.

`searches.yaml` is a transitional Israel-regional example with generic public role names. The inherited ATS filter currently requires that regional setting; changing only the locations can silently eliminate ATS matches. Lane 2 must replace both search selection and posting-location filtering with DB/profile-driven geography before this is stranger-ready.

## Local run

```bash
python3 scraper/harvest.py --profile profile.yaml --output-dir data/job-feed --max-pages 1
```

Enable reviewed public ATS sources with `--sources comeet,greenhouse,lever,workable`. Luna annotation is best-effort and uses `codex exec` when that binary is available; deterministic JSONL output remains available when it is not.

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
