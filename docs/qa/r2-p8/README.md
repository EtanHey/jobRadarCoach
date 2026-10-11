# R2 P8 UI evidence

Status: implementation verified locally with synthetic data; review and deployment pending.

The header uses singular/plural role counts. Status labels beside single-digit scores wrap without clipping or broken words. Collapsed filters show individually clearable selections. Tabs have native tooltips and accessible descriptions; the new-roles action explains that Show refreshes the list. The mobile badge and sheet use the same selection list.

## Verification

- Valid baseline browser run: 20 failures across 1440/1100/900/390 (singular heading, missing tab help, clipped status, missing chips and clear action). New-roles accessibility test also failed before its change.
- Readability regression: four failures before adding the status column minimum width.
- Final capped browser run: all four widths passed, zero page/console errors; 1638 MB peak, 35 seconds. Real headless Chromium/WebGL with a local synthetic globe style and point; no external tiles or credentials.
- Existing capped toolbar regression: 1100/900/1440/1280/390 passed; desktop controls remain within two rows; 1822 MB peak, 13 seconds.
- Unit tests: 292 server/library + 22 client passed. Browser component tests: 3 passed. TypeScript and ESLint passed.

Run from `ui/`: `npm ci`, `npx playwright install chromium --only-shell`, then `npm run test:ui-polish`. It runs under the repository's portable 3072 MB / 600 second cap. CI runs it sequentially after the e2e pilot. Synthetic copies remain under ignored `.e2e/`.

## Screenshots

| Width | Collapsed filters and low score |
| --- | --- |
| 1440 | [Screenshot](polish-1440.png) |
| 1100 | [Screenshot](polish-1100.png) |
| 900 | [Screenshot](polish-900.png) |
| 390 | [Screenshot](polish-390.png) |

[Mobile sheet: two active filters](filters-390.png) · [Headless synthetic globe](globe-smoke.png)

## Surface check

- Entry points: list heading, card status, tab selection, collapsed toolbar, mobile sheet, new-roles refresh; verified by browser/component tests.
- Clients: desktop 1440/1100/900, mobile 390 and headless Chromium; synthetic local runtime only.
- Providers: synthetic jobs/globe responses and map style; no production API, account or analysis service used.
- Contracts: no API/schema changes; badge and chips share the sheet's selections, existing saved collapse preference retained.
- Reverse states: expand/collapse, clear each filter independently, clear to zero, reset view and persistence checked.
- Connection modes: credential-free isolated fixture; hosted/logged-in behavior and deployment remain lead-owned.
- Docs: committed screenshots and these reproduction instructions.

## PR #455 fix round 1

Status: locally verified; independent re-review and deployment pending.

Collapsed chips, the desktop/mobile Filters badge and the sheet count now use `viewForBoardQuery`. Not scored suspends Found in the past and Availability, so neither appears as an active archive constraint. Clearing a remaining archive chip edits the saved view without persisting archive overrides; All roles restores the suspended selections.

- RED at `2d16b87`: the reviewer's assertion failed at 1440/1280/1100/900/390, solely because the ignored time window appeared as an archive chip (1788 MB peak, 37 seconds).
- GREEN: all existing UI-polish assertions plus archive badge/chip, non-default availability, archive clear, persisted preference preservation and return-to-All-roles checks passed at all five widths; zero page/console errors (1886 MB peak, 25 seconds). Expanded desktop filters stayed within two rows at 1280/1100/900.
- Preference/accessibility tests: 12 passed. TypeScript and targeted ESLint passed.
- Visual inspection: [mobile archive with one effective chip](archive-390.png) and [desktop archive after clearing Location](archive-cleared-1440.png).
- Surface check: desktop/mobile toolbar and sheet count share effective selections; saved controls remain the edit source. Browser tests cover entry, exit and clear-to-zero. API/schema/provider contracts are unchanged. Real local Chromium uses synthetic jobs and offline map fixtures; hosted/logged-in verification and production service operations remain lead-owned.
