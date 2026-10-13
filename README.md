# Alcohol Label Verifier

Checks alcohol beverage label images against the data in the label application: brand, class/type, alcohol content, net contents, producer name and address, country of origin, and the government health warning. For each field it returns **Pass**, **Needs review** or **Fail**, with what the application says, what the label says, the rule applied and the reason. Batch mode checks hundreds of labels from a spreadsheet.

**Live demo (no login): https://ttb-label-verifier.salmonsky-e6ff55c6.eastus2.azurecontainerapps.io**

![Single-label check: form with an example loaded](docs/screenshots/1-form.png)

## Try it in 30 seconds

1. Open the demo. Under **Try an example**, keep "Compliant bourbon label" and click **Load example**, then **Verify label**. Every field passes, including the warning's bold heading.
2. Pick **Warning heading not in capitals** and verify: the warning fails, and **Show warning details** shows the word-level difference.
3. Pick **Brand spelled differently (MAPLE CREAK)**: the brand is **Needs review**, with `CREEK → CREAK` shown.
4. Open **Check a batch** and click **Load a sample batch (5 labels)**, then **Check all labels**. Click a label name to see its full result. **Export results (CSV)** downloads the table.

On a phone, **Take a photo** opens the rear camera.

| Result with a warning violation | Batch results, problems first |
|---|---|
| ![Fail with warning diff](docs/screenshots/3-result-fail-warning.png) | ![Batch](docs/screenshots/5-batch.png) |

## Evaluation criteria: evidence

| Criterion | Evidence |
|---|---|
| Correctness and completeness | Every field in the brief is checked ([rules](#how-verification-works)). Measured on the deployed app, [validation report](docs/validation-report.md): **0 false passes** with either engine, and **0 false fails** with the cloud engine, over 220 labeled checks. 363 automated tests (`tests/`). |
| Code quality and organization | `app/core` is a pure, typed library (pydantic models, no web code): readers behind one `LabelExtractor` interface, rules in `app/core/rules` and `warning.py`, every threshold in `config.py`. `app/api` is a thin FastAPI layer. |
| Appropriate technical choices | One container, no database, no build step: [design decisions](#design-decisions-and-trade-offs). The cloud model costs about $0.0012 per label (measured) and has a hard daily cap. |
| User experience and error handling | One page, two tabs, one-click examples and sample batch. Plain-English errors (wrong file type, too large, unreadable, busy, rate limited). Color always paired with an icon and a word. Works on phones: the result table stacks into cards and the camera opens. Checked in a real browser (Chromium) at desktop and iPhone sizes. |
| Attention to requirements | [Requirement-to-feature map](#requirements-map) below: 5-second target, exact warning, judgment on cosmetic differences, batch of 200 to 300, imperfect photos, nothing stored, works behind a firewall. |
| Creative problem-solving | **The AI reads, rules decide.** The model never sees the application, so it can't be biased toward the expected answer. **Two readers** (cloud vision and offline OCR) cross-check the warning, catching a model that "corrects" altered text. **Bold type is measured from the pixels** as well as asked of the model. **Needs review** for anything unverified. Front and back labels are merged. The batch runs in the browser, so the server stays stateless. |

## Requirements map

| Stakeholder ask | How it is met | Evidence |
|---|---|---|
| Field-by-field comparison | 7 fields, each with expected, found, rule and reason | `app/core/rules`, `tests/unit` |
| Warning word for word, "GOVERNMENT WARNING:" in capitals and bold | Exact, case-sensitive comparison with a word diff. Heading capitals and colon. Bold from the model **and** a pixel measurement, which must agree | `app/core/warning.py`, `app/core/stroke.py` |
| About 5 seconds per label | Cloud: 3.5 s typical (p50), 4.6 s for the slowest 5% (p95), measured. Offline: 1.1 s / 1.5 s. The time is shown on every result | [Measured performance](#measured-performance) |
| Usable without training, many users over 50 | 18 px base font, large buttons, one-click examples, plain-English reasons, colors always with an icon and a word | Screenshots; browser test |
| Judgment on cosmetic differences | `STONE'S THROW` = `Stone's Throw` (Pass). A one-letter difference is **Needs review** with the letters shown, never an automatic Pass | `tests/unit/test_text_fields.py` |
| Batch of 200 to 300 labels | CSV template, checked for problems before starting, 6 at a time, live progress, problems first, retry, CSV export | 300-label run below |
| Imperfect photos | EXIF rotation, deskew, contrast. Blur, glare and darkness are reported. Hard-to-read photos are Needs review, never Fail | 31 simulated photos in the validation report |
| Nothing sensitive stored | No database; nothing written to disk except the web framework's temporary buffer for large uploads; no request logs | [Data handling](#data-handling) |
| Works where cloud AI is blocked | Offline OCR engine (Tesseract) in the same container | `EXTRACTOR=local` |

## How verification works

The engine **reads** each image with a reader and then **decides** with deterministic rules. Readers never see the application data.

| Field | Rule |
|---|---|
| Brand name | Exact match ignoring capitalization, punctuation and spacing. A spelling difference, even one letter, is Needs review with the differing words shown |
| Class/type, producer | Every expected word present (ignoring capitalization and punctuation). "Distilled and Bottled by …", "Brewed and Canned by …" and similar prefixes are allowed. A near-miss spelling is Needs review |
| Alcohol content | Numeric ABV comparison; any proof on the label must equal 2 × ABV |
| Net contents | Converted to mL (mL, cL, L, fl oz), within 0.5% |
| Country of origin | Imports only: "Product of …", "Made in …", "Imported from …" |
| Government warning | Exact, case-sensitive wording (27 CFR 16.21); "GOVERNMENT WARNING:" in capitals with the colon; heading bold, body not bold (27 CFR 16.22) |

**Safeguards against false passes**

- **Similar is not the same.** Fuzzy similarity only decides between Needs review and Fail. It never produces a Pass.
- **No Pass from a stray hit.** Text found on the label confirms a field only on its own line, outside the warning, and not on a line already used by another field. Numbers count only next to their unit (`%`, `Proof`, `mL`, …).
- **Two readers for the warning.** With the cloud engine, offline OCR reads the same image in parallel. If the offline reader doubts the wording the model read as exact, the result is Needs review. A simulated model that always returns the textbook warning and formatting never gets a violating label to Pass (`tests/test_fixtures_vision_sim.py`, `tests/test_photo_fixtures.py`).
- **Bold is measured, not just asked.** The stroke thickness of "GOVERNMENT WARNING:" is compared with the body words on the same printed line: a bold heading over regular text measures about 1.7×, the same weight about 1.0×. A bold Pass needs the model's judgment **and** the measurement to agree. Live testing showed why: the model called a regular-weight heading bold 1 time in 5, and called an all-bold warning "heading bold, body regular". On small print in photos the measurement often can't confirm bold, so those warnings are Needs review: unverified never means Pass.
- **Front and back labels.** Up to 4 images per label are read in parallel and merged. Unless the reviewer ticks **These images show every side of the label**, anything not found is Needs review ("it may be on the back label"), not Fail. A statement that is present but wrong is Fail either way.

**Safeguards against false fails**

- **Reading noise is not a violation.** Differences only in punctuation, only in spacing (`ofthe`), in a few letters the reader was unsure of, or anywhere when the offline reader's confidence over the warning is low, are Needs review with the reason. Confident readings of changed, added or missing words are Fail.
- **Text the model marks illegible** (glare, blur) is Needs review, not a wording difference.
- **Unreadable images are never Failed:** they are Needs review with "Request a better image".

## Engines

| Engine | Setting | What it does |
|---|---|---|
| Cloud AI | `EXTRACTOR=auto` (default) | Azure OpenAI gpt-4.1-mini (vision), structured JSON output, temperature 0, 8 s timeout, told to transcribe and never correct. Offline OCR runs alongside as the cross-check and the fallback: if the cloud is slow, unavailable, rate-limited or over its daily cap, the offline result is used and the reviewer is told. |
| Offline OCR | `EXTRACTOR=local` | Tesseract 5 in the same container. Nothing leaves the server. It can't see bold type, so a label that passes everything else is Needs review for the warning. |

## Measured performance

All numbers are **measured** on the deployed app (Azure Container Apps, 1 vCPU / 2 GiB per replica, 1 to 2 replicas, East US 2), from a client outside Azure, so they include the internet round trip. Build `720b52a`, 2026-10-13.

| | Cloud AI | Offline OCR |
|---|---|---|
| Single label, p50 / p95 round trip | 3.5 s / 4.6 s | 1.1 s / 1.5 s |
| Server time, p50 / p95 | 3.2 s / 4.2 s | 0.8 s / 1.8 s |
| 300-label batch through the UI (cloud engine, 6 at a time; build `e27a76a`) | **6 min 52 s** (44 labels/min), 0 errors, 299 of 300 read by the cloud engine, 0 false passes, 0 false fails | n/a |
| Cost per label (list price, measured tokens) | about $0.0012 (≈1,860 input + ≈250 output tokens) | none beyond hosting |

- The first request after the app has scaled to zero waited **33 s** for a cold start (measured with min replicas 0). The review deployment keeps one replica warm.
- The batch ran on one replica. Each replica checks 3 labels at a time and paces cloud calls at 46 per minute, so about 45 labels per minute is that replica's ceiling. A second replica would roughly double throughput; with the platform's default scaling rule it starts only at 10 concurrent requests, and the batch sends 6.
- Single-image labels only. A front + back pair takes about 0.5 s longer (both images are read in parallel). The slowest single request measured was 7.1 s.

## Validation summary

[Full report with every label](docs/validation-report.md). Run with `scripts/run_accuracy.py`. The fixtures are synthetic, with hand-written truth: 24 flat rendered labels (`clean`), and 31 simulated photographs (`photos`) with curvature, angle, glare, blur, small print, unusual fonts and front/back pairs. They are **not real photos of real products**.

| Engine | Set | Labels | As expected | False pass | False fail | Detection (Fail) | Flagged (not Pass) | Needs review | p50 / p95 round trip | Server p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| Cloud AI | clean | 48 | 48/48 (100%) | 0/28 (0%) | 0/20 (0%) | 20/24 (83%) | 24/24 (100%) | 8/44 (18%) | 3.0 s / 4.9 s | 2.8 s / 4.2 s |
| Cloud AI | photos | 62 | 62/62 (100%) | 0/36 (0%) | 0/26 (0%) | 28/32 (88%) | 32/32 (100%) | 30/58 (52%) | 3.8 s / 4.6 s | 3.4 s / 4.2 s |
| Offline OCR | clean | 48 | 48/48 (100%) | 0/28 (0%) | 0/20 (0%) | 18/24 (75%) | 24/24 (100%) | 26/44 (59%) | 0.7 s / 1.0 s | 0.5 s / 0.6 s |
| Offline OCR | photos | 62 | 60/62 (97%) | 0/36 (0%) | 2/26 (8%) | 24/32 (75%) | 32/32 (100%) | 32/58 (55%) | 1.3 s / 2.1 s | 1.0 s / 1.8 s |

- **False pass** counts violations, and labels whose right answer is Needs review, that were marked Pass. **Needs review** is out of labels whose right answer is Pass or Fail. The gate for the cloud engine is 20% or less.
- **Gates (cloud engine):** false pass 0% met; false fail 0% met; Needs review ≤ 20% met on the flat labels (18%) but **not** on the simulated photos (52%): bold on small photo print usually can't be confirmed, and the offline cross-check often doubts small print. Detection as Fail is 83% / 88% against a 90% target. Every violation that was not a Fail was flagged Needs review: bold-type violations on photos, and a brand found only in the address line, which needs review by design. The offline engine's 2 false fails are one photo where glare hides a word of the class/type, read the same way in both repetitions.

Key thresholds (all in `app/core/config.py`):
- brand: exact words to pass, similarity 85 or more is Needs review;
- warning: 3 or fewer letter edits on words the reader was unsure of, or average OCR confidence under 86%, is Needs review;
- bold: heading/body stroke ratio of 1.4 or more confirms bold, 1.15 or less means the same weight;
- unreadable below 55% reader confidence.

## Design decisions and trade-offs

- **AI reads, rules decide.** A vision model is far better than OCR on curved, glossy, decorative labels, but it can be confidently wrong and it knows what a warning "should" say. So it only transcribes, blind to the application, and deterministic, tested rules make every decision.
- **Needs review over guessing.** A wrong Pass is the costly error for a compliance reviewer. Anything unverified (bold type the pixels can't confirm, a one-letter brand difference, a missing back label) goes to a person with the reason. The cost is a higher review rate on poor photos.
- **Local and cloud engines.** The offline engine covers networks that block cloud AI and is the automatic fallback. It is also the independent second reader in cloud mode.
- **The batch runs in the browser.** The browser sends 6 requests at a time to the same single-label API. The server holds no job state, so it scales across replicas and survives restarts, and progress is live with no polling infrastructure.
- **No database, no storage.** Nothing to secure, back up or purge; results live in the reviewer's browser and their CSV export.
- **Stack:** Python 3.12, FastAPI, Tesseract, OpenCV, rapidfuzz; plain HTML/JS/CSS (no build step); one Docker image built with `az acr build`.

## Usage protection (server side)

The public demo has no login, so spending is limited in the server; budget alerts only notify.
- **Uploads:** 10 MB per image, up to 4 images per label, enforced while the request streams in. JPEG, PNG and WebP only. The browser converts phone HEIC photos and very large images to JPEG where it can.
- **Rate limit:** 120 checks per minute per IP. Only the address added by the platform's own proxy is trusted.
- **Daily cloud cap:** 1,000 cloud calls per replica (2 replicas maximum). Past the cap, the app uses offline OCR and says so.
- **Cloud pacing** keeps calls within the model quota, calibrated from Azure's own count (about 1,300 tokens per label): 46 per minute per replica. A single check over the pace uses offline OCR at once; batch requests wait up to 45 s for a cloud slot. After a 429, the app waits as long as Azure asks.
- **Concurrency:** at most 3 checks at a time per replica; others wait up to 30 s, then get "server is busy". The batch client retries those automatically.

## Data handling

The app keeps nothing after a request: no database, no files, and label content is never logged.
- Uploads over 1 MB are briefly buffered to a temporary file by the web framework, deleted when the request ends.
- **Cloud engine:** each image is sent to Azure OpenAI (regional Standard deployment, East US 2). Microsoft states that prompts and completions are not used to train or improve models and are not stored in the model. By default, Azure OpenAI abuse monitoring may store prompts and completions flagged as potentially abusive, in the resource's geography, for review by authorized Microsoft employees. Customers approved for modified abuse monitoring can turn that off. Sources, checked 2026-10-13: [Data, privacy, and security](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/data-privacy); [Abuse monitoring](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring). This deployment uses the default.
- **Logs:** the Container Apps environment has no log destination, so application and request logs are not retained. API responses include the model's token counts for cost tracking.

## Production considerations

- **Hosting:** the same container runs in Azure Government, or on a customer-hosted server with `EXTRACTOR=local` and no outbound calls.
- **Data retention:** for sensitive submissions, apply for modified abuse monitoring, or use the offline engine.
- **Access:** sign-in would be Microsoft Entra ID in front of the app (Container Apps built-in authentication); the per-IP limits would become per-user.
- **Audit trail:** if needed, results could be written to an approved records system instead of only exported to CSV.

## Limitations and assumptions

- **Fixtures are synthetic.** The simulated photos approximate glare, curvature and small print, but real photos of real products have not been measured. Real label images would be the first thing to add.
- **Bold on small print in photos is often Needs review.** At about 13 px text height, regular and bold condensed type measure nearly the same. Clean, high-resolution images confirm bold reliably.
- **Needs review rate on photos is high** (about half of the simulated photos with the cloud engine). That's the cost of the bold and two-reader safeguards. On flat label images it is within the 20% gate.
- **Offline OCR on photos** misreads small and curved print. Low-confidence readings are Needs review rather than Fail, but a word lost under glare can still cause a Fail.
- **Not checked:** warning type size, legibility and contrast, placement ("separate and apart", same field of vision), and mandatory statements not in the form (e.g. sulfites, color additives, age statements). Wine and beer rules beyond these fields are not covered.
- **Not attempted:** perspective correction of strongly angled photos, and live video scanning.

## Run locally

Requires Python 3.12 and Tesseract 5 (`sudo apt-get install -y tesseract-ocr` on Debian/Ubuntu).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
EXTRACTOR=local .venv/bin/uvicorn app.api.main:app --port 8710
```

Open http://127.0.0.1:8710 and load an example. For the cloud engine, set `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`, and sign in with `az login` (or set `AZURE_OPENAI_API_KEY` for local development). See `.env.example`.

- **Tests:** `.venv/bin/python -m pytest` (about 4 minutes). The `ocr`-marked tests run real Tesseract on every fixture; skip them with `-m "not ocr"`.
- **Fixtures:** `python scripts/make_fixtures.py` and `python scripts/make_photo_fixtures.py` regenerate them.
- **Accuracy:** `python scripts/run_accuracy.py <url> --provider azure --provider local --report docs/validation-report.md` measures a running instance.
- **Docker:** `docker build -t ttb-label-verifier . && docker run -p 8000:8000 -e EXTRACTOR=local ttb-label-verifier` runs the offline engine with no Azure settings. The deployed image is built from this Dockerfile with `az acr build`; the development VPS has no local Docker, so `docker run` itself was not tested there.

## Deployment

The Azure infrastructure was provisioned separately: a resource group, Azure OpenAI with a gpt-4.1-mini Standard deployment, a Basic container registry, Container Apps, and a managed identity with least-privilege roles. The app is deployed onto it with:

```bash
python deploy/azure/app_deploy.py check  -g rg-ttb-label-verifier            # read-only
python deploy/azure/app_deploy.py deploy -g rg-ttb-label-verifier --confirm  # az acr build + containerapp update
```

`check` verifies:
- the model, deployment type and keyless (Entra ID) sign-in;
- the managed identity's roles (Cognitive Services OpenAI User on Azure OpenAI, AcrPull on the registry);
- ingress, container size, replica range and quota.

`deploy` builds the image in the registry and updates the existing app. It clears a placeholder start command if there is one, and sets the cloud pace from the quota. Its smoke test calls only `/api/health` and `/api/config`, never the model. `deploy/azure/deploy.sh` is a reference script for provisioning from scratch.

## Layout

```
app/core/        typed library: models, engine (multi-image merge), rules, warning, stroke (bold), quality, readers
app/api/         FastAPI: /api/verify, /api/health, /api/config, usage protection, plain-English errors
app/web/         one static page (vanilla JS, no build step), CSV template, examples
deploy/azure/    app_deploy.py (app-only deploy onto existing resources), deploy.sh (reference provisioning)
scripts/         fixture generators, run_accuracy.py, OFL fonts used for the photo fixtures
tests/           unit, API, real-OCR fixture tests, simulated-reader tests, photo safety tests
docs/            validation report, screenshots
```

## AI tools used in development

This project was built with Claude Code (Anthropic) as a coding assistant, working from an approved design: it wrote code, tests, fixtures and documentation under review. All verification results above are measured, and every rule is covered by tests. At run time the app uses Azure OpenAI gpt-4.1-mini only to transcribe label images.
