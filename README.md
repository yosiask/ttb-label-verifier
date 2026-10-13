# Alcohol Label Verifier

Checks an alcohol beverage label image against the data in its application (brand, class/type, alcohol content, net contents, producer, country of origin, government warning). It returns a field-by-field checklist: **Pass**, **Needs review** or **Fail**, with the expected value, the value found on the label, the rule applied, and the reason.

> **Status: Milestone 2, deployed.** Live at **https://ttb-label-verifier.salmonsky-e6ff55c6.eastus2.azurecontainerapps.io** (no login). Single-label checks work with the cloud vision engine and the offline OCR engine. Batch mode and the full write-up come in later milestones; this README will be completed in Milestone 5.

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
- **Bold needs two independent sources to agree.** The cloud model's bold judgment is checked against a pixel measurement: the stroke thickness of "GOVERNMENT WARNING:" compared with the body text, taken from the offline OCR that already runs alongside. A bold heading over a regular body measures about 1.8-2.0x; same weight measures about 1.0x. If the model and the pixels disagree, the result is Needs review. This was added after live testing caught the model calling a regular-weight heading bold in 1 of 5 runs. The measurement is skipped on blurry photos, where blur thickens every stroke.

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
- Daily cap on cloud AI calls (default 1,000 per replica, at most 2 replicas). Past the cap, the app switches to offline OCR and says so.
- Cloud calls are paced per replica (`CLOUD_REQUESTS_PER_MINUTE`) to stay inside the model deployment's tokens-per-minute quota. If Azure still answers 429, the app waits as long as Azure asks (`retry-after`) without calling again. Either way, a label checked in that moment uses offline OCR at once, with a note, instead of waiting. The output budget (`max_tokens` 1000) is kept small because Azure counts it against the quota on every call.
- At most 4 checks at a time per replica; extra requests wait up to 30 s, then get a plain "server is busy" message.
- Hard tokens-per-minute quota on the Azure OpenAI deployment, enforced by Azure.

All thresholds live in `app/core/config.py`. They are the starting values from the design brief and will be tuned on the fixtures in Milestone 4.

## Layout

```
app/core/        pure library (no FastAPI): models, engine, rules, warning, extractors, preprocessing, quality
app/api/         FastAPI: /api/verify, /api/health, /api/config, usage protection, plain-English errors
deploy/azure/    app_deploy.py: check + deploy the app onto existing Azure resources (creates nothing)
                 deploy.sh: reference from-scratch provisioning (not used for the review deployment)
app/web/         one static page, vanilla JS, no build step
scripts/         make_fixtures.py renders synthetic labels with hand-written expected results
tests/           unit, API, fixture tests through real OCR, and a simulated-vision fixture run
```

## Deploying onto existing Azure resources

The review deployment's infrastructure (resource group, Azure OpenAI with a gpt-4.1-mini Standard deployment, Basic container registry, Container Apps, managed identity and role assignments) is provisioned separately. The app is deployed onto it with:

```bash
python deploy/azure/app_deploy.py check  -g rg-ttb-label-verifier            # read-only
python deploy/azure/app_deploy.py deploy -g rg-ttb-label-verifier            # dry run: prints the settings
python deploy/azure/app_deploy.py deploy -g rg-ttb-label-verifier --confirm  # az acr build + containerapp update
```

`check` finds the resources and confirms that the app can run on them:
- the model, deployment type and auth (Entra ID only);
- that the app's managed identity has Cognitive Services OpenAI User on the Azure OpenAI resource and AcrPull on the registry;
- external ingress, container size and replica range;
- what the model quota allows per minute.

`deploy` builds the image in the registry and points the existing app at it. It sets the listen port to the app's existing ingress target port, and the cloud pace from the quota and maximum replicas. It also sets `AZURE_CLIENT_ID` when the app uses a user-assigned identity. Its smoke test calls only `/api/health` and `/api/config`, so deploying never starts model inference.

## Data handling

The app keeps nothing after a request. There is no database, and label content is never logged. During a request:

- Uploads larger than 1 MB are briefly buffered to a temporary file by the web framework. The file is deleted when the request ends.
- With the cloud engine, the image is sent to Azure OpenAI (regional Standard deployment in East US 2) to be read. Microsoft states that prompts and completions are not used to train or improve models and are not stored in the model. By default, Azure OpenAI abuse monitoring may store prompts and completions flagged as potentially abusive, in the resource's geography, for review by authorized Microsoft employees. Customers approved for modified abuse monitoring can turn that storage off ([Data, privacy, and security](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/data-privacy); [Abuse monitoring](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring), both checked 2026-10-13). This deployment uses the default.
- The Container Apps environment has no log destination, so application and request logs are not retained. The API response includes the model's token counts for cost tracking, but no label content is logged.

## Initial live results (Milestone 2)

**Measured** on the deployed app, 2026-10-13, image `022ab51`. Requests came from a VPS outside Azure, so round-trip times include the internet. These are synthetic fixture labels, not real label photos. Real-looking labels and threshold tuning are Milestone 4.

| Engine | Labels | As expected | False pass | False fail | Needs review | Round trip p50 / p95 | Server p50 / p95 |
|---|---|---|---|---|---|---|---|
| Cloud (gpt-4.1-mini) | 24 fixtures x 2 | 48/48 | 0 | 0 | 11 (23%) | 4.2 s / 4.9 s | 4.0 s / 4.7 s |
| Offline OCR (same container) | 24 fixtures x 1 | 24/24 | 0 | 0 | 15 (63%) | 0.7 s / 1.0 s | 0.5 s / 0.6 s |

- Cloud Needs review breakdown: 8 of the 11 are fixtures designed to need review (a brand one letter off, a brand found only in the address, an unreadable image, a regular-weight heading). The other 3 are degraded photos (glare, low resolution). Clear compliant labels: all Pass.
- Earlier live runs (with stricter checks added since): before the bold measurement, the regular-weight-heading label passed 1 time in 5. After it, 0 passes in 11 runs, all Needs review. The all-bold warning failed 11 of 11 times, and the clean label passed 11 of 11.
- Tokens per cloud call (measured): about 1,820 input and 245 output. At list prices (input $0.44/M, output $1.76/M) that is about **$0.0012 per label**.
- Cold start: with minimum replicas 0, the app scales to zero after about 5 idle minutes. The next request then took **33 s** (measured), against about 3 s warm. Keeping one replica running avoids this.

Simulated results (`tests/test_fixtures_vision_sim.py`, a scripted "perfect" reader plus real OCR) are separate. They check the rules and safeguards, not the model.

## Not checked by this tool

Government warning type size, legibility and contrast, placement ("separate and apart", same field of vision), and mandatory statements that are not in the form.
