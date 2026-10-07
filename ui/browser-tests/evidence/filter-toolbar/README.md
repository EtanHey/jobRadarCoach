# Filter toolbar synthetic browser evidence

Base: `2e75fe32175fa9365f4dbb86a5fb1a184d11e151`.

Run from `ui` with:

```sh
GLOBE_QA_OUTPUT=<evidence-directory> /Users/etanheyman/Gits/jobRadarCoach/docs.local/tools/run-suite-capped.sh browser-tests/filter-toolbar.mjs 3072 240
```

The suite starts its own credential-free fixture app on a fresh loopback port, blocks external requests, and uses Chromium headless-shell. No production API, login, or local-analysis service is involved.

RED: `FILTER_BASELINE=1 FILTER_LAYOUT_ONLY=1` loads the base toolbar into the disposable copy. Both 1100px and 900px fail with three rows. GREEN: 1440px has one row; 1280px, 1100px and 900px have two. At 390px the existing sheet remains available.

The suite also verifies collapse/expand across reload, active badge updates, a long selected label, Reset reopening the filters, no horizontal overflow, no page errors, and mobile Show roles restoring focus.

Screenshots were visually inspected. This is local synthetic UI evidence; hosted deployment and globe-rendering QA are outside this lane.

| Width | Screenshot |
| --- | --- |
| 1440 | [Toolbar](toolbar-1440.png) |
| 1280 | [Toolbar](toolbar-1280.png) |
| 1100 | [Toolbar](toolbar-1100.png) |
| 900 | [Toolbar](toolbar-900.png) |
| 390 | [Toolbar](toolbar-390.png), [drawer](toolbar-390-drawer.png) |

## PR #432 fix round 1

At review head `bcf5408`, the new same-row label-top assertion failed at 1100px
(pipeline 169px, sibling labels 171px) and 900px (239px versus 241px). Making the
pipeline label block-level passes that assertion at both widths. The full capped
browser suite passes all five widths, including collapse persistence, long labels,
Reset, mobile focus return, overflow and page-error checks. The refreshed 1100/900
screenshots were visually inspected. Scoped ESLint and TypeScript also pass.

The optional Reset behavior change is deferred: `isDefaultBoardPreferences` also
controls persistence, so ignoring collapse there would discard saved collapse state.
