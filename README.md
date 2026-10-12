# Alcohol Label Verifier

Checks an alcohol beverage label image against the data in its application (brand, class/type, alcohol content, net contents, producer, country of origin, government warning). It returns a field-by-field checklist: **Pass**, **Needs review** or **Fail**, with the expected value, the value found on the label, the rule applied, and the reason.

> **Status: Milestone 1 (single-label slice, offline OCR).** The cloud vision engine, deployment, batch mode and the full write-up come in later milestones. This README will be completed in Milestone 5.

## Run locally

Requires Python 3.12 and Tesseract 5 (`sudo apt-get install -y tesseract-ocr` on Debian/Ubuntu).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/make_fixtures.py        # renders the test labels and UI examples
EXTRACTOR=local .venv/bin/uvicorn app.api.main:app --port 8710
```

Open http://127.0.0.1:8710, choose an example, click **Load example**, then **Verify label**.

Tests: `.venv/bin/python -m pytest` (the `ocr`-marked tests run real Tesseract on every fixture; skip them with `-m "not ocr"`).

## How verification works

The engine **reads** the label with an extraction provider and then **decides** with deterministic rules. Providers never see the application data, so they cannot be biased toward the expected answer.

| Field | Rule |
|---|---|
| Brand name | Case/punctuation-insensitive match, fuzzy search (`partial_ratio`) |
| Class/type, producer | Word-set match; every expected word must be present |
| Alcohol content | Numeric ABV comparison; any proof on the label must equal 2 × ABV |
| Net contents | Converted to mL (mL, cL, L, fl oz), within 0.5% |
| Country of origin | Imports only; "Product of …", "Made in …", "Imported from …" |
| Government warning | Exact, case-sensitive wording (27 CFR 16.21); "GOVERNMENT WARNING:" in capitals with colon; bold checked where the engine can see type weight (27 CFR 16.22) |

Safeguards:

- **No false pass from a stray hit.** Text found on the label only confirms a field when it sits on its own line (the match covers at least 80% of the line), is outside the warning statement, and is not the line that matched another field. Otherwise the result is Needs review.
- **Numbers need their unit.** ABV must sit next to `%`, `Alc`, `Vol`, `ABV` or `Proof`. Volume must sit next to `mL`, `cL`, `L` or `fl oz`. A bare number never counts, and neither does a misread like `4S%`.
- **OCR noise vs real violation.** If the warning differs only by a few letters (3 edits or fewer) in words the OCR was unsure of, the result is Needs review. Whole words added, removed or changed are a Fail.
- **Unreadable images are never Failed.** They come back as Needs review with "Request a better image."
- **Unverified never means Pass.** The offline engine cannot see bold type, so with offline OCR, a label whose other checks all pass is **Needs review** for the warning. That is by design.

All thresholds live in `app/core/config.py`. They are the starting values from the design brief and will be tuned on the fixtures in Milestone 4.

## Layout

```
app/core/        pure library (no FastAPI): models, engine, rules, warning, extractors, preprocessing
app/api/         FastAPI: /api/verify, /api/health, /api/config, plain-English error handling
app/web/         one static page, vanilla JS, no build step
scripts/         make_fixtures.py renders synthetic labels with hand-written expected results
tests/           unit, API, and fixture-driven tests through real OCR
```

## Data handling

The app stores nothing. The image and extracted text exist in memory for the one request, then are dropped. There is no database, and label content is never logged.

## Not checked by this tool

Government warning type size, legibility and contrast, placement ("separate and apart", same field of vision), and mandatory statements that are not in the form.
