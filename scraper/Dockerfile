# 1. Base: a ready-made Linux with Python 3.12, small variant
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1

# 2. Working directory inside the box; every later path is relative to it
WORKDIR /app

# 3. Copy only the portable scraper. A user's profile is mounted at runtime.
COPY scraper/ /app/scraper/

# 4. Don't run as root: make a user, hand it the folder, switch to it
RUN useradd --create-home radar \
    && mkdir -p /app/data/job-feed \
    && chown -R radar:radar /app
USER radar

# 5. The one command that runs when the box starts
ENTRYPOINT ["python", "/app/scraper/harvest.py", "--output-dir", "/app/data/job-feed/"]
CMD []
