# Analyzer decisions

This document records the reviewed, occurrence-specific DeepSource dispositions for the Lane 1 source relocation. The repository keeps all analyzer severities blocking and does not use blanket, file-wide, or rule-wide suppression.

## Intentional fail-loud fixture lookups (`PTC-W0063`)

Fifteen test occurrences use `next()` to select a required fixture record or consume a controlled clock. A missing record or exhausted clock is a broken test setup and must surface as a test error rather than become a silent skip:

- `test_annotate.py`: the named posting fixture lookup.
- `test_harvest.py`: eight named negative-rule lookups and two controlled-clock reads.
- `test_liveness.py`: two required persisted-row lookups.
- `test_sources.py`: the malformed-timestamp row and named Workable row lookups.

Each occurrence carries its own `skipcq: PTC-W0063` annotation and adjacent reason.

## Protocol-shaped test doubles (`PYL-R0201`)

Six instance methods intentionally model APIs consumed by production code; converting them to static methods would misrepresent those protocols:

- `test_jd_fetch.py`: `FakeHeaders.get_content_charset` models the urllib headers API.
- `test_sources.py`: three `Response.geturl` and two `Response.read` methods model urllib responses.

Each method carries its own `skipcq: PYL-R0201` annotation and adjacent reason.

## Validation and API compatibility

- `source_registry.py`: the annotated `BAN-B101` assertion performs type narrowing only after unconditional `_validate_entry` rejection. It is not the validation boundary.
- `test_annotate.py`: the annotated `PYL-W0622` parameter intentionally mirrors the keyword-only `input` parameter of `subprocess.run`.
- `harvest.py`: the annotated `PYL-R1716` expression directly states the documented rule that more than half of attempted JD fetches failed.

## Acknowledged complexity debt (`PY-R1000`)

The following thirteen functions retain validation or control flow relocated into this repository. They are acknowledged debt, not false positives, and have not been refactored in this cleanup:

- `annotate.py`: `_load_safe_profile_contract`, `_validated_annotation`, `calibrate`.
- `harvest.py`: `_score_candidate`, `load_profile_contract`, `write_summary`, `_validated_pipeline_annotation`, `run_pipeline`.
- `source_registry.py`: `_validate_entry`, `_validate_public_https_url`, `detect_supported_ats`, `_endpoint_payload_is_valid`, `import_candidates`.

Each function carries its own `skipcq: PY-R1000` annotation and adjacent relocation rationale.

Later cleanup is bounded by ownership: classifier and profile-related functions may be reconsidered when their feature lanes change them; registry and deterministic legacy functions belong in a separate maintenance change with behavior-preserving tests. This analyzer-cleanup slice does not redesign either group.
