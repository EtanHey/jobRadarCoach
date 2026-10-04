# Optional scorer title-family guard

Profiles can add `target_role_families` to `candidate.scorer_calibration`.
This optional, nonempty list accepts `frontend`, `fullstack`, `product`,
`backend`, `data`, `ml`, and `analytics`. For example, a synthetic candidate
might choose `["frontend", "fullstack", "product"]`. Choose families from the
candidate's actual role preferences; technology familiarity is a separate input.

When an explicit title family is outside that list, the deterministic adapter
caps `fit_score` at 59 and records `title_role_mismatch`, even if the model
extracts a full-stack role focus or finds matching technologies in the JD.
Existing stricter calibration caps still apply. Scores never increase.
The existing score bands derive `stretch`/`review` from a capped score; an
explicit authoritative human recommendation is still preserved.

Title parsing recognizes explicit role phrases. `Data Product Engineer`
belongs to `data`, while `AI Product Engineer` belongs to `product`.
Front-end, back-end, and full-stack spelling variants are normalized.
Titles naming both frontend and backend belong to `fullstack`.
Generic software titles, unknown titles, and domain labels such as
`Software Engineer - Data Visualization UI` abstain from the title guard;
the JD and existing calibration rules still determine their fit.
This is bounded phrase recognition, not a complete occupational taxonomy.

Omitting the list keeps the prior calibrated request and behavior. Profiles
without calibration retain their existing request bytes. This change does
not opt a profile in, update stored scores, choose a Pursue cutoff, or release
the production analysis service.

An offline replay of the frozen 40-row cohort on the latest stored 1b scores
changed no scores: at Pursue cutoffs 60/65/70, agreement remained 15/22,
15/22, and 10/22; exact accuracy remained 24/40, 25/40, and 20/40. One
unscored row stayed in all denominators. Against the original stored reference,
there was one Pursue-to-Maybe regression at cutoffs 60/65 (agreement fell by
1/22 and exact accuracy by 1/40); there were none at cutoff 70. This is an
in-sample replay under an explicit family-config scenario, not provider,
extraction, or production validation. The cutoff and profile opt-in remain
operator decisions. The changed original-reference row has Pursue gold and
substantive full-stack responsibilities; the title policy conflicts with that
prior label. Resolve that preference conflict before enabling it.
