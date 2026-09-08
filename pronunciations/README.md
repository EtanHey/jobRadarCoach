# English say-as dictionary

`pronunciations.en.json` is a UTF-8 JSON object from exact, case-sensitive written terms to English spoken forms. It is deliberately engine-neutral: callers decide whether matching is whole-term or substring based, and may layer engine-specific syntax outside this file.

## Scope

The source inventory contains 1,075 distinct technology terms: 272 with a verified catalog mark, 191 generic concepts, and 612 without a verified catalog mark. This dictionary curates only terms likely to be mishandled by English TTS: initialisms, punctuation-heavy language/framework names, a few vendor names, and public company/place names present in the read-only job API corpus. Ordinary words and already-readable product names are intentionally unchanged and therefore absent.

The API-derived QA snapshot pass projected only public professional fields (`company`, `location`, and `stack`) from 256 job summaries. It is a bounded snapshot, not evidence of the current live API. No job descriptions, candidate/profile fields, contacts, or private-source data were copied into this file.

## Pronunciation provenance

Two spellings have explicit first-party pronunciation guidance:

- `PostgreSQL` follows the PostgreSQL Press FAQ: `post-GRES-que-ell`. <https://www.postgresql.org/about/press/faq/>
- `Django` follows the Django FAQ: `JANG-oh`, with a silent `D`. <https://docs.djangoproject.com/en/5.2/faq/general/>

The requested company names are confirmed against their first-party sites, but those pages do not publish phonetic guidance: [Guidde](https://www.guidde.com/), [Cyera](https://www.cyera.com/), [Sett](https://www.sett.ai/), and [Nagomi Security](https://nagomisecurity.com/). Their entries—and the other company/place phonetics—are practical English approximations, not vendor-confirmed or engine-auditioned. A later voice QA pass should treat these as the review set rather than as verified pronunciations.

The remaining entries, including `NGINX` / `engine X`, use conventional English letter names or readable respellings without a first-party verification claim. `SQL` is intentionally spelled out as `S Q L`; callers needing a house style such as “sequel” can override it. Exact observed variants such as `Nginx`/`NGINX` are separate keys because lookup is case-sensitive; aliases may intentionally share a spoken value.

## Inventory accounting

- Included: actual say-as overrides for acronyms/initialisms, punctuation-sensitive technical names, common TTS traps, selected public company names, and Israeli place names.
- Left unchanged: generic concepts and phrases, ordinary English words, product names whose spelling is already a safe reading, long compound phrases, version-specific variants that inherit an included base term, and ambiguous low-frequency terms without enough evidence.
- Excluded: private candidate context, job-description prose, personal names, and any data from Daphna or ScoutMole.

This dataset has not been tested against a live TTS engine and makes no claim about a particular engine's output.
