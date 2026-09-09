# One status command

`jrc status` reports the scrape scheduler first, then the voice runtime's current mode, health and ownership. It exits nonzero if either is unhealthy or unavailable. A failed latest scheduled attempt cannot be hidden by an older successful run or a healthy voice session.

`jrc run` and `jrc run --qa` still replace the foreground process directly; Ctrl-C retains its existing cleanup behavior. This status integration neither starts nor stops the scheduler. Detailed sanitized JSON remains available from `python3 scripts/pipeline_scheduler_status.py`.
