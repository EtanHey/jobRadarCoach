# Maintaining employer identity pins

Status: current maintenance instructions. The reviewed pins live in
`ui/lib/company-logo-identity-pins.ts`; generated identities and source-company
bindings live in `ui/lib/company-logo-identities.json` and
`ui/lib/company-logo-source-bindings.json`.

For a name shared by multiple employers, set `collision: true` and record the
verified employer domains and structured company identifiers (`linkedin:slug`,
`greenhouse:tenant`, etc.). A bare company name or a JD mention does not establish
identity. Preserve conflicting/missing evidence as initials. Wrong artwork and
placeholder names remain in `company-logo-overrides.ts` as initials overrides.

1. Verify the posting's employer-heading link or its ATS tenant and the catalog
   asset's provenance. Record the source and verification in a reviewed document.
2. Add the canonical company key and verified identifiers to the pins file. Do
   not put raw JDs, contacts, credentials, or URL query tokens in committed data.
3. From `ui`, regenerate using a SELECT-only private snapshot and saved source
   pages: `node --import tsx ../scripts/build-logo-source-bindings.ts
   <snapshot.json> <source-page-dir>...`. The generator checks manifest page hashes,
   adds catalog posting IDs, and writes the two generated JSON maps. It neither
   fetches providers nor modifies the database.
4. Inspect the generated diff and run `npm test`. In particular, the binding and
   logo tests must retain ordinary names, keep verified DoiT marks, and reject
   Doit's conflicting company identifier. New collisions need equivalent tests.

An identity pin supplies employer evidence; it does not verify the pixels of a
new logo asset. Inspect any changed artwork separately on cards, drawer and rail.
