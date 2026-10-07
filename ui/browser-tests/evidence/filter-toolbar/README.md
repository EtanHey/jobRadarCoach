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
