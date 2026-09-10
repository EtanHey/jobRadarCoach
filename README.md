# Job Radar Coach

Job Radar Coach is a private job-search dashboard and data pipeline. It collects
public job postings, keeps application status and profile preferences in one
place, and scores jobs against an evidence-bounded professional profile.

The standalone architecture has four parts:

- **Vercel** serves the authenticated Next.js dashboard.
- **Hosted Supabase** owns Postgres data, owner authentication, Vault, and Cron.
- **GitHub Actions** runs the Python scraper in the cloud against public sources,
  so fetching does not depend on a Mac being awake.
- **A local CLI** performs LLM extraction and scoring with the owner's local
  model subscription. Hosted scorer cutover is unfinished.

The cloud scraper and Supabase scheduling source are merged. Their presence in
the repository does not prove that the schedule is active or that a hosted run
has persisted fresh rows; activation and live receipts are separate release
steps.

DialogKit is the separate generic text and voice agent. Job Radar Coach owns the
job-domain API, validation, and configuration that DialogKit may consume. The
legacy embedded agent integration is preserved as legacy evidence and is not
being converted into DialogKit inside this repository.

See [setup](docs/setup.md) for development and deployment contracts and
[end state](docs/end-state.md) for the product and ownership boundaries.
