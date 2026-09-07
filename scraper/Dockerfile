# 1. Base: a ready-made Linux with Python 3.12, small variant
FROM python:3.12-slim
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1

# 2. Working directory inside the box; every later path is relative to it
WORKDIR /app

# 3. Install bounded dependencies, then copy only the portable runtime sources.
RUN python -m pip install --no-cache-dir "psycopg[binary]==3.3.5" "jsonschema==4.26.0"

COPY build/install_codex.py /tmp/install_codex.py
RUN python /tmp/install_codex.py "$TARGETARCH" \
    && rm /tmp/install_codex.py \
    && codex --version

COPY scraper/ /app/scraper/
COPY extractor/core.py extractor/evidence.py extractor/payload.py extractor/persistence.py extractor/job.py /app/extractor/

# 4. Don't run as root: make a user, hand it the folder, switch to it
RUN useradd --create-home radar \
    && mkdir -p /app/data/job-feed \
    && chown -R radar:radar /app
USER radar

# 5. The one command that runs when the box starts
ENTRYPOINT ["python", "/app/scraper/harvest.py", "--output-dir", "/app/data/job-feed/"]
CMD []
