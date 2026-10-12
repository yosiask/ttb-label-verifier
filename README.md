# Alcohol Label Verifier

Checks an alcohol beverage label image against the data in its application (brand, class/type, alcohol content, net contents, producer, country of origin, government warning). It returns a field-by-field checklist: **Pass**, **Needs review** or **Fail**, with the expected value, the value found on the label, the rule applied, and the reason.

> **Status: Milestone 2 in progress.** The single-label check works with offline OCR. The cloud vision engine is built and tested against a mocked client, but it is not deployed yet: the Azure resources are waiting for approval. Batch mode and the full write-up come in later milestones; this README will be completed in Milestone 5.

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
| Brand name | Exact match ignoring capitalization, punctuation and spacing (`STONE'S THROW` = `Stone's Throw`). A spelling difference, even one letter, is Needs review with the differing words shown, never an automatic Pass |
| Class/type, producer | Every expected word present exactly (ignoring capitalization and punctuation); a near-miss spelling is Needs review |
| Alcohol content | Numeric ABV comparison; any proof on the label must equal 2 × ABV |
| Net contents | Converted to mL (mL, cL, L, fl oz), within 0.5% |
| Country of origin | Imports only; "Product of …", "Made in …", "Imported from …" |
| Government warning | Exact, case-sensitive wording (27 CFR 16.21); "GOVERNMENT WARNING:" in capitals with colon; bold checked where the engine can see type weight (27 CFR 16.22) |

Safeguards:

- **No false pass from a stray hit.** Text found on the label only confirms a field when it sits on its own line (the match covers at least 80% of the line), is outside the warning statement, and is not the line that matched another field. Otherwise the result is Needs review.
- **Numbers need their unit.** ABV must sit next to `%`, `Alc`, `Vol`, `ABV` or `Proof`. Volume must sit next to `mL`, `cL`, `L` or `fl oz`. A bare number never counts, and neither does a misread like `4S%`.
- **Similar is not the same.** Fuzzy similarity only decides between Needs review (a near miss that may be a misread or a real difference) and Fail. It never produces a Pass on its own.
- **Reading noise vs real violation.** If the warning differs only by a few letters (3 edits or fewer) in words the reader was unsure of, or only in punctuation (readers often confuse `,` and `.` on small print), the result is Needs review. Whole words added, removed or changed are a Fail.
- **Two readers for the warning.** With the cloud engine, offline OCR reads the same image in parallel. A vision model can "auto-correct" an altered warning to the standard wording it knows. If the two readers disagree about the warning text, the result is Needs review, never Pass. Tests simulate a model that always returns the standard warning and confirm that no violating fixture passes.
- **Unreadable images are never Failed.** They come back as Needs review with "Request a better image."
- **Unverified never means Pass.** The offline engine cannot see bold type, so with offline OCR, a label whose other checks all pass is **Needs review** for the warning. That is by design.

## Engines

| Engine | Setting | What it does |
|---|---|---|
| Cloud AI | `EXTRACTOR=auto` (default) | Azure OpenAI vision model, structured JSON output, temperature 0, 8 s hard timeout. Reads bold type. Offline OCR runs alongside as a cross-check. If the cloud is slow, unavailable or over its daily cap, the offline result is used and the reviewer is told. |
| Offline OCR | `EXTRACTOR=local` | Tesseract on the server. Nothing leaves the machine, so it works on networks that block cloud AI. It cannot see bold type. |

Image quality: blur, darkness, low contrast and small images are reported in plain English with the result. A very small image (under 300 px) is treated as unreadable.

## Usage protection (server side)

The public demo has no login, so spending is limited in the server, not just by budget alerts (alerts only notify):

- 10 MB per image, enforced while the request streams in, before it is parsed. JPEG, PNG and WebP only.
- Per-IP rate limit (default 120 checks/minute). Behind Azure Container Apps, only the address added by the platform's own proxy is trusted.
- Daily cap on cloud AI calls (default 1,000 per replica, at most 3 replicas). Past the cap, the app switches to offline OCR and says so.
- At most 4 checks at a time per replica; extra requests wait up to 30 s, then get a plain "server is busy" message.
- Hard tokens-per-minute quota on the Azure OpenAI deployment, enforced by Azure.

All thresholds live in `app/core/config.py`. They are the starting values from the design brief and will be tuned on the fixtures in Milestone 4.

## Layout

```
app/core/        pure library (no FastAPI): models, engine, rules, warning, extractors, preprocessing, quality
app/api/         FastAPI: /api/verify, /api/health, /api/config, usage protection, plain-English errors
deploy/azure/    deploy.sh (az CLI, not yet run) ; Dockerfile builds in Azure with `az acr build`
app/web/         one static page, vanilla JS, no build step
scripts/         make_fixtures.py renders synthetic labels with hand-written expected results
tests/           unit, API, fixture tests through real OCR, and a simulated-vision fixture run
```

## Data handling

The app keeps nothing after a request. There is no database, and label content is never logged. During a request:

- Uploads larger than 1 MB are briefly buffered to a temporary file by the web framework. The file is deleted when the request ends.
- With the cloud engine, the image is sent to Azure OpenAI to be read. Azure OpenAI does not use it for training, but by default it may keep prompts for a limited time for abuse monitoring. (Microsoft's current wording will be confirmed before deployment.)

## Not checked by this tool

Government warning type size, legibility and contrast, placement ("separate and apart", same field of vision), and mandatory statements that are not in the form.
