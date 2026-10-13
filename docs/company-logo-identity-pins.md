# Maintaining employer identity pins

Status: current. Reviewed pins: `ui/lib/company-logo-identity-pins.ts`.
Generated output: `company-logo-identities.json` and `company-logo-source-bindings.json` in `ui/lib`.
For a shared name, set `collision: true` and record verified employer domains and
structured identifiers (`linkedin:slug`, `greenhouse:tenant`). Bare names and JD
mentions do not establish identity. Missing/conflicting evidence keeps initials;
wrong-artwork and placeholder pins remain in `company-logo-overrides.ts`.

1. Verify the posting employer-heading link/ATS tenant and catalog asset provenance.
   Record the source and verification in a reviewed document.
2. Add canonical keys and verified identifiers to the pins file. Keep raw JDs,
   contacts, credentials and URL query tokens out of committed data.
3. From `ui`, regenerate from a SELECT-only private snapshot and saved pages:
   `node --import tsx ../scripts/build-logo-source-bindings.ts <snapshot.json> <source-page-dir>...`.
   The generator checks manifest page hashes and writes the two JSON maps without
   fetching providers or modifying the database.
4. Inspect the diff and run `npm test`: retain ordinary names and verified DoiT
   marks; reject conflicting Doit identifiers. Add equivalent tests for new collisions.
Identity evidence does not verify new artwork; inspect cards, drawer and rail separately.
