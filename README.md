# Job Radar Coach

Job Radar Coach is a private job-search dashboard and data pipeline. It collects
public job postings, keeps application status and profile preferences in one
place, and scores jobs against an evidence-bounded professional profile.

The standalone architecture has four parts:

- **Vercel** serves the authenticated Next.js dashboard.
- **Hosted Supabase** owns Postgres data, owner authentication, and access controls.
- **GitHub Actions** runs the Python scraper in the cloud against public sources,
  on a native six-hour schedule, so fetching does not depend on a Mac being awake.
- **A local CLI** performs LLM extraction and scoring with the owner's local
  model subscription. Hosted scorer cutover is unfinished.

The cloud workflow includes its schedule in source. Its presence does not prove
that a scheduled run executed or persisted fresh rows; live receipts are a
separate release step.

DialogKit is the separate generic text and voice agent. Job Radar Coach owns the
job-domain API, validation, and configuration that DialogKit may consume. The
legacy embedded agent integration is preserved as legacy evidence and is not
being converted into DialogKit inside this repository.

See the [cloud pipeline](docs/cloud-pipeline.md) for the complete data flow and
scheduling contract, [setup](docs/setup.md) for deployment, and
[end state](docs/end-state.md) for product and ownership boundaries.
