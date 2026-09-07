# 1. Base: a ready-made Linux with Python 3.12, small variant
FROM python:3.12-slim

# 2. Working directory inside the box; every later path is relative to it
WORKDIR /app

# 3. Copy in what the script reads. Paths are relative to the build context (repo root)
COPY scripts/job-feed/ /app/scripts/job-feed/
COPY references/profile-export.yaml /app/references/

# 4. Don't run as root: make a user, hand it the folder, switch to it
RUN useradd --create-home radar && chown -R radar /app
USER radar

# 5. The one command that runs when the box starts
ENTRYPOINT ["python", "scripts/job-feed/harvest.py", "--output-dir", "/app/data/job-feed/"]
CMD []
