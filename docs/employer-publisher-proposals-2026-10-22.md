# Employer publisher list proposals — 2026-10-22

STATUS: PROPOSED; lead review required. The active Python and UI catalogs are unchanged.

Resolver 13 uses client wording only for offline nominations. A company-wide badge needs reviewed list membership or a complete third-person staffing statement about that publisher. These proposals use primary business sources, independently of job-description wording.

- **Griting** — nominate: its [official site](https://www.griting.ai/) advertises managed hiring for a success fee, validated shortlists and hiring support, and identifies advertised opportunities as partner-company roles. It also sells talent evaluation software; review that mixed business before approving a company-wide badge.
- **מרטנס | Mertens – מקבוצת מלם תים** — nominate: the [parent company's Mertens page](https://www.malamteam.com/שירותי-פיתוח-ומיקור-חוץ/מרטנס-שירותי-מומחים-ויועצים-לארגון-של/) describes placement of consultants and specialists at client organizations; the existing resolver already excludes the English `Mertens - MalamTeam` identity as a reviewed staffing candidate.
- **Ladders** — defer: its [about page](https://www.theladders.com/about-us) and [recruiter FAQ](https://recruit.theladders.com/faqs) describe a job-search and recruiter-access platform; that supports publisher/reposter status but does not establish an unambiguous staffing agency under this round's precision rule.
- **Jobgether** — exclude from agency additions: its [terms](https://sitemap.jobgether.com/terms-of-use), updated September 7, 2026, expressly disclaim acting as an employer, recruitment agency or employment intermediary; the platform aggregates third-party opportunities.

The unchanged 658-row snapshot loses 16 labels against round 11: Jobgether 12, Ladders 3 and Mertens 1. Against `8b76cf6`, the loss is 19: the same 16 plus Griting 1 and Ladders 2 already lost in round 11. All retain a null hiring employer and an unknown relationship. No list additions have been activated, so these are proposal-only survival counts. Individual row IDs and verbatim nomination/evidence lines are in the lead's local P7 round-12 receipts.

Approve each candidate explicitly, then change `scraper/employer_publishers.py` and `ui/lib/employer-publishers.json` together and replay the snapshot. A future publisher/reposter category should be decided separately from the agency badge.
