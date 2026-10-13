"use strict";

const STATUS = {
  pass: { icon: "✔", word: "Pass" },
  needs_review: { icon: "⚠", word: "Needs review" },
  fail: { icon: "✖", word: "Fail" },
  "n/a": { icon: "–", word: "Not applicable" },
  error: { icon: "!", word: "Not checked" },
};
const FIELD_LABELS = {
  brand_name: "Brand name",
  class_type: "Class / type",
  alcohol_content: "Alcohol content",
  net_contents: "Net contents",
  producer_name_address: "Producer name and address",
  country_of_origin: "Country of origin",
  government_warning: "Government warning",
};
const ENGINE_LABELS = { auto: "Automatic", azure: "Cloud AI", local: "Offline OCR", local_ocr: "Offline OCR", azure_vision: "Cloud AI" };
const FORM_FIELDS = ["brand_name", "class_type", "alcohol_content", "net_contents", "producer_name_address", "country_of_origin", "beverage_type"];
const ALLOWED = ["image/jpeg", "image/png", "image/webp"];
const MAX_IMAGES = 4;
const BATCH_CONCURRENCY = 6;
const BATCH_MAX_ROWS = 500;

const $ = (id) => document.getElementById(id);
let images = []; // selected files for the single check, in order
let maxUploadMb = 10;
let cloudReady = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function statusClass(s) { return s === "n/a" ? "st-na" : `st-${s}`; }

function pill(status) {
  const s = STATUS[status] || STATUS["n/a"];
  return el("span", { class: `pill ${statusClass(status)}` }, el("span", { "aria-hidden": "true" }, s.icon), s.word);
}

function showError(message, id = "form-error") {
  const box = $(id);
  box.textContent = message;
  box.hidden = !message;
}

// ---------------------------------------------------------------- tabs
function selectTab(which) {
  for (const [tab, panel] of [["tab-single", "single-panel"], ["tab-batch", "batch-panel"]]) {
    const on = tab === which;
    $(tab).setAttribute("aria-selected", String(on));
    $(tab).tabIndex = on ? 0 : -1;
    $(panel).hidden = !on;
  }
}
$("tab-single").addEventListener("click", () => selectTab("tab-single"));
$("tab-batch").addEventListener("click", () => selectTab("tab-batch"));
for (const id of ["tab-single", "tab-batch"]) {
  $(id).addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const next = id === "tab-single" ? "tab-batch" : "tab-single";
      selectTab(next);
      $(next).focus();
    }
  });
}

// ---------------------------------------------------------------- images
// Phones may give HEIC photos or very large files. Where the browser can decode the image,
// re-save it as JPEG with a long edge of at most 3000 px: smaller uploads, same legibility.
async function normalizeImage(file) {
  const big = file.size > 4 * 1024 * 1024;
  if (ALLOWED.includes(file.type) && !big) return file;
  if (typeof createImageBitmap !== "function" || typeof OffscreenCanvas === "undefined") {
    if (ALLOWED.includes(file.type)) return file;
    throw new Error("unsupported");
  }
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, 3000 / Math.max(bitmap.width, bitmap.height));
  const canvas = new OffscreenCanvas(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.9 });
  const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
  return new File([blob], name, { type: "image/jpeg" });
}

async function addImages(fileList) {
  showError("");
  for (const raw of fileList) {
    if (images.length >= MAX_IMAGES) {
      showError(`Use at most ${MAX_IMAGES} images of one label (for example front, back and neck).`);
      break;
    }
    let file;
    try {
      file = await normalizeImage(raw);
    } catch {
      showError(`"${raw.name}" is not a supported image. Choose a JPEG, PNG or WebP photo of the label.`);
      continue;
    }
    if (file.size > maxUploadMb * 1024 * 1024) {
      showError(`"${raw.name}" is larger than ${maxUploadMb} MB. Use a smaller photo.`);
      continue;
    }
    images.push(file);
  }
  renderThumbs();
}

function renderThumbs() {
  const list = $("thumbs");
  for (const img of list.querySelectorAll("img")) URL.revokeObjectURL(img.src);
  list.replaceChildren();
  images.forEach((file, i) => {
    const url = URL.createObjectURL(file);
    const remove = el("button", { type: "button", class: "link-button", "aria-label": `Remove image ${i + 1}` }, "Remove");
    remove.addEventListener("click", () => { images.splice(i, 1); renderThumbs(); });
    list.append(el("li", {}, el("img", { src: url, alt: `Image ${i + 1}: ${file.name}` }),
      el("span", {}, `Image ${i + 1}`), remove));
  });
  const preview = $("preview");
  if (images.length === 1) {
    preview.src = URL.createObjectURL(images[0]);
    preview.hidden = false;
    list.hidden = true;
  } else {
    preview.hidden = true;
    list.hidden = images.length === 0;
  }
  $("drop-text").hidden = images.length > 0;
  $("file-name").textContent = images.length ? `Selected: ${images.map((f) => f.name).join(", ")}` : "";
  $("add-image").hidden = images.length === 0 || images.length >= MAX_IMAGES;
  $("clear-images").hidden = images.length === 0;
}

const dropZone = $("drop-zone");
// Copy the FileList before clearing the input: clearing empties the live list.
$("image-input").addEventListener("change", (e) => { addImages([...e.target.files]); e.target.value = ""; });
$("camera-input").addEventListener("change", (e) => { addImages([...e.target.files]); e.target.value = ""; });
$("add-image").addEventListener("click", () => $("image-input").click());
$("clear-images").addEventListener("click", () => { images = []; renderThumbs(); });
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("image-input").click(); }
});
["dragenter", "dragover"].forEach((t) => dropZone.addEventListener(t, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((t) => dropZone.addEventListener(t, (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); }));
dropZone.addEventListener("drop", (e) => addImages([...e.dataTransfer.files]));
// The camera button only where there is one (touch devices); elsewhere the file picker covers it.
if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) $("camera-button").hidden = false;

$("is_import").addEventListener("change", (e) => { $("country-field").hidden = !e.target.checked; });

// ---------------------------------------------------------------- examples
$("load-example").addEventListener("click", async () => {
  const name = $("example-select").value;
  showError("");
  try {
    const [meta, img] = await Promise.all([
      fetch(`examples/${name}.json`).then((r) => { if (!r.ok) throw new Error(); return r.json(); }),
      fetch(`examples/${name}.png`).then((r) => { if (!r.ok) throw new Error(); return r.blob(); }),
    ]);
    const app = meta.application;
    for (const f of FORM_FIELDS) $(f).value = app[f] ?? "";
    $("is_import").checked = !!app.is_import;
    $("country-field").hidden = !app.is_import;
    $("all_sides").checked = true; // each example image is the whole label
    images = [new File([img], `${name}.png`, { type: "image/png" })];
    renderThumbs();
    $("results").hidden = true;
  } catch {
    showError("The example could not be loaded. Reload the page and try again.");
  }
});

// ---------------------------------------------------------------- engines
function fillEngines(select, cfg) {
  const cloud = cfg && cfg.providers.azure && cfg.cloud_available_today;
  const options = [
    ["auto", "Cloud AI (checks bold type; uses offline OCR if the cloud is unavailable)", cloud],
    ["local", "Offline OCR (works without internet)", !cfg || cfg.providers.local],
  ];
  for (const [value, label, enabled] of options) {
    const opt = el("option", { value }, enabled ? label : `${label} – not available`);
    if (!enabled) opt.disabled = true;
    select.append(opt);
  }
  select.value = cloud ? "auto" : "local";
}

async function loadConfig() {
  const select = $("provider");
  try {
    const cfg = await fetch("api/config").then((r) => r.json());
    maxUploadMb = cfg.max_upload_mb || 10;
    cloudReady = cfg.providers.azure && cfg.cloud_available_today;
    fillEngines(select, cfg);
    fillEngines($("batch-provider"), cfg);
    const note = () => {
      $("provider-note").textContent = select.value === "local"
        ? "Offline OCR cannot see bold type, so a label that passes everything else shows “Needs review” for the warning."
        : "The label image is sent to the cloud AI service to be read. It is not stored by this app.";
    };
    select.addEventListener("change", note);
    note();
  } catch {
    select.append(el("option", { value: "local" }, "Offline OCR"));
    $("batch-provider").append(el("option", { value: "local" }, "Offline OCR"));
  }
}

// ---------------------------------------------------------------- single check
function readForm() {
  const app = {};
  const missing = [];
  for (const f of FORM_FIELDS) {
    const v = $(f).value.trim();
    app[f] = v || null;
    const input = $(f);
    if (input.required && !v) missing.push(input.labels[0].textContent);
  }
  app.is_import = $("is_import").checked;
  if (app.is_import && !app.country_of_origin) missing.push("Country of origin");
  return { app, missing };
}

$("verify-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  if (!images.length) { showError("Please choose a label image first."); return; }
  const { app, missing } = readForm();
  if (missing.length) { showError(`Please fill in: ${missing.join(", ")}.`); return; }

  const body = new FormData();
  for (const f of images) body.append("image", f);
  body.append("application", JSON.stringify(app));
  body.append("provider", $("provider").value);
  body.append("all_sides", $("all_sides").checked ? "true" : "false");

  const btn = $("verify-btn");
  btn.disabled = true;
  btn.textContent = images.length > 1 ? `Checking ${images.length} images…` : "Checking label…";
  const started = performance.now();
  try {
    const resp = await fetch("api/verify", { method: "POST", body });
    let data = null;
    try { data = await resp.json(); } catch { /* non-JSON */ }
    if (!resp.ok) {
      showError((data && data.message) || "The label could not be checked. Please try again.");
      return;
    }
    renderResult($("results"), data, (performance.now() - started) / 1000);
    $("results").hidden = false;
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch {
    showError("Could not reach the server. Check your connection and try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Verify label";
  }
});

// ---------------------------------------------------------------- result rendering
function renderDiff(diff) {
  const box = el("div", { class: "diff-text" });
  for (const d of diff) {
    if (d.op === "equal") box.append(d.text, " ");
    else if (d.op === "missing") box.append(el("del", { title: "Missing from label" }, d.text), " ");
    else if (d.op === "extra") box.append(el("ins", { title: "Extra on label" }, d.text), " ");
    else box.append(el("del", { title: "Required text" }, d.expected), " ", el("ins", { title: "Label text" }, d.found), " ");
  }
  return box;
}

// The warning is long: show its start here; the full text is in the word diff under "Why".
function labelSays(c) {
  if (c.found === null || c.found === undefined) return c.status === "n/a" ? "—" : "Not found";
  if (c.field !== "government_warning") return c.found;
  const words = c.found.split(/\s+/);
  return words.length > 6 ? `${words.slice(0, 6).join(" ")} … (full text under “Show warning details”)` : c.found;
}

function renderResult(root, r, roundTripSeconds) {
  const s = STATUS[r.overall];
  const banner = root.querySelector(".banner");
  banner.className = `banner ${statusClass(r.overall)}`;
  const parts = [];
  if (roundTripSeconds !== null) parts.push(`Checked in ${roundTripSeconds.toFixed(1)} s (server ${(r.timings_ms.total / 1000).toFixed(1)} s)`);
  parts.push(`Engine: ${ENGINE_LABELS[r.provider] || r.provider}`);
  if (r.image_count > 1) parts.push(`${r.image_count} images`);
  banner.replaceChildren(
    el("span", { class: "icon", "aria-hidden": "true" }, s.icon),
    el("span", {}, s.word),
    el("span", { class: "time" }, parts.join(" · ")),
  );
  const msg = root.querySelector(".result-message");
  msg.textContent = r.message || "";
  msg.hidden = !r.message;

  const tbody = root.querySelector("tbody");
  tbody.replaceChildren();
  for (const c of r.checks) {
    const why = el("td", { "data-label": "Why" }, c.reason);
    if (c.field === "government_warning" && c.details) {
      const det = el("details", { class: "diff" }, el("summary", {}, "Show warning details"));
      const steps = el("ul", { class: "steps" });
      for (const st of c.details.steps || []) {
        steps.append(el("li", {}, `${(STATUS[st.status] || {}).word || st.status} – ${st.step}: ${st.reason}`));
      }
      det.append(steps);
      const legend = "Struck-through text is required but missing; underlined text is on the label but not in the required wording.";
      if (c.details.diff && c.details.diff.length) {
        det.append(el("p", { class: "diff-legend" }, legend));
        det.append(renderDiff(c.details.diff));
      } else if (c.found) {
        det.append(el("p", { class: "diff-legend" }, "Warning text read from the label:"), el("div", { class: "diff-text" }, c.found));
      }
      const xc = c.details.cross_check;
      if (c.details.readers_disagree && xc) {
        det.append(el("p", { class: "diff-legend" }, `The offline reader saw: ${xc.reason}`));
        if (xc.diff && xc.diff.length) det.append(renderDiff(xc.diff));
      }
      why.append(det);
    }
    const sd = c.details && c.details.spelling_differences;
    if (sd && sd.length) {
      const box = el("div", { class: "diff-text" });
      for (const d of sd) box.append(el("del", { title: "Application" }, d.expected), " → ", d.found ? el("ins", { title: "Label" }, d.found) : "(not on label)", el("br"));
      why.append(box);
    }
    tbody.append(el("tr", {},
      el("td", { "data-label": "Result" }, pill(c.status)),
      el("th", { scope: "row" }, FIELD_LABELS[c.field] || c.field),
      el("td", { class: "expected", "data-label": "Application says" }, c.field === "government_warning" ? "Exact text required by 27 CFR 16.21" : (c.expected ?? "—")),
      el("td", { class: "found", "data-label": "Label says" }, labelSays(c)),
      why,
    ));
  }
  const list = root.querySelector("#not-checked-list");
  if (list) list.replaceChildren(...r.not_checked.map((t) => el("li", {}, t)));
}

// ---------------------------------------------------------------- batch: CSV
const CSV_REQUIRED = ["filename", "brand_name", "class_type", "alcohol_content", "net_contents", "producer_name_address"];
const CSV_OPTIONAL = ["country_of_origin", "is_import", "beverage_type", "all_sides"];

function parseCsv(text) {
  // RFC 4180: quoted fields, doubled quotes, commas and newlines inside quotes.
  const rows = [];
  let row = [], field = "", i = 0, quoted = false;
  text = text.replace(/^﻿/, "");
  while (i < text.length) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 2; continue; }
      if (ch === '"') { quoted = false; i++; continue; }
      field += ch; i++; continue;
    }
    if (ch === '"' && field === "") { quoted = true; i++; continue; }
    if (ch === ",") { row.push(field); field = ""; i++; continue; }
    if (ch === "\r") { i++; continue; }
    if (ch === "\n") { row.push(field); rows.push(row); row = []; field = ""; i++; continue; }
    field += ch; i++;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

const truthy = (v) => ["yes", "y", "true", "1", "x"].includes((v || "").trim().toLowerCase());

function buildBatch(csvText, files) {
  const problems = [];
  const rows = parseCsv(csvText);
  if (!rows.length) return { items: [], problems: ["The CSV file is empty."] };
  const header = rows[0].map((h) => h.trim().toLowerCase());
  const missingCols = CSV_REQUIRED.filter((c) => !header.includes(c));
  if (missingCols.length) {
    return { items: [], problems: [`The CSV is missing these columns: ${missingCols.join(", ")}. Start from the template.`] };
  }
  const byName = new Map(files.map((f) => [f.name.toLowerCase(), f]));
  const used = new Set();
  const items = [];
  rows.slice(1).forEach((cells, idx) => {
    const line = idx + 2;
    const get = (c) => (cells[header.indexOf(c)] ?? "").trim();
    const names = get("filename").split(/[;|]/).map((n) => n.trim()).filter(Boolean);
    const rowProblems = [];
    if (!names.length) rowProblems.push("no file name");
    if (names.length > MAX_IMAGES) rowProblems.push(`more than ${MAX_IMAGES} images`);
    const imgs = [];
    for (const n of names) {
      const f = byName.get(n.toLowerCase());
      if (!f) rowProblems.push(`image "${n}" was not selected`);
      else { imgs.push(f); used.add(n.toLowerCase()); }
    }
    const app = {
      brand_name: get("brand_name"), class_type: get("class_type"), alcohol_content: get("alcohol_content"),
      net_contents: get("net_contents"), producer_name_address: get("producer_name_address"),
      country_of_origin: get("country_of_origin") || null, is_import: truthy(get("is_import")),
      beverage_type: (get("beverage_type") || "spirits").toLowerCase(),
    };
    const empty = CSV_REQUIRED.slice(1).filter((c) => !app[c]);
    if (empty.length) rowProblems.push(`empty: ${empty.join(", ")}`);
    if (app.is_import && !app.country_of_origin) rowProblems.push("imported but no country_of_origin");
    if (!["spirits", "wine", "beer"].includes(app.beverage_type)) rowProblems.push(`beverage_type "${app.beverage_type}" (use spirits, wine or beer)`);
    const item = { line, label: names.join(" + ") || `row ${line}`, images: imgs, app, allSides: truthy(get("all_sides")) };
    if (rowProblems.length) {
      item.skipped = `Row ${line}: ${rowProblems.join("; ")}.`;
      problems.push(item.skipped);
    }
    items.push(item);
  });
  if (items.length > BATCH_MAX_ROWS) {
    return { items: [], problems: [`The CSV has ${items.length} labels; the limit is ${BATCH_MAX_ROWS} per batch. Split it into smaller files.`] };
  }
  const unused = files.filter((f) => !used.has(f.name.toLowerCase()));
  if (unused.length) problems.push(`${unused.length} image(s) are not listed in the CSV and will be ignored: ${unused.slice(0, 5).map((f) => f.name).join(", ")}${unused.length > 5 ? ", …" : ""}.`);
  return { items, problems };
}

// ---------------------------------------------------------------- batch: selection
let batch = { csvText: null, csvName: null, files: [], items: [], running: false, stop: false };

async function addBatchFiles(fileList) {
  showError("", "batch-error");
  for (const f of fileList) {
    if (f.name.toLowerCase().endsWith(".csv") || f.type === "text/csv") {
      batch.csvText = await f.text();
      batch.csvName = f.name;
    } else if (ALLOWED.includes(f.type)) {
      batch.files = batch.files.filter((x) => x.name.toLowerCase() !== f.name.toLowerCase()).concat([f]);
    }
  }
  validateBatch();
}

function validateBatch() {
  const summary = $("batch-summary");
  const probs = $("batch-problems");
  if (!batch.csvText) {
    summary.hidden = false;
    summary.textContent = `${batch.files.length} image(s) selected. Now add the CSV file.`;
    probs.hidden = true;
    $("batch-start").disabled = true;
    return;
  }
  const { items, problems } = buildBatch(batch.csvText, batch.files);
  batch.items = items;
  const ready = items.filter((i) => !i.skipped).length;
  summary.hidden = false;
  summary.textContent = `${batch.csvName}: ${items.length} label(s), ${batch.files.length} image(s). ` +
    (ready ? `${ready} ready to check.` : "None can be checked yet.");
  probs.hidden = !problems.length;
  probs.replaceChildren(el("p", {}, el("strong", {}, "Please look at these before starting"),
    " (rows with problems are skipped; the others still run):"),
  el("ul", {}, ...problems.slice(0, 50).map((p) => el("li", {}, p))),
  problems.length > 50 ? el("p", {}, `…and ${problems.length - 50} more.`) : "");
  $("batch-start").disabled = !ready || batch.running;
}

const batchDrop = $("batch-drop");
$("batch-files").addEventListener("change", (e) => { addBatchFiles([...e.target.files]); e.target.value = ""; });
batchDrop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("batch-files").click(); } });
["dragenter", "dragover"].forEach((t) => batchDrop.addEventListener(t, (e) => { e.preventDefault(); batchDrop.classList.add("dragover"); }));
["dragleave", "drop"].forEach((t) => batchDrop.addEventListener(t, (e) => { e.preventDefault(); batchDrop.classList.remove("dragover"); }));
batchDrop.addEventListener("drop", (e) => addBatchFiles([...e.dataTransfer.files]));

const SAMPLE = ["clean_spirits", "brand_case_diff", "abv_mismatch", "warning_title_case", "brand_one_letter_off"];
$("batch-sample").addEventListener("click", async () => {
  showError("", "batch-error");
  try {
    const metas = await Promise.all(SAMPLE.map((n) => fetch(`examples/${n}.json`).then((r) => r.json())));
    const blobs = await Promise.all(SAMPLE.map((n) => fetch(`examples/${n}.png`).then((r) => r.blob())));
    const cols = ["filename", ...CSV_REQUIRED.slice(1), ...CSV_OPTIONAL];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [cols.join(",")].concat(metas.map((m, i) => {
      const a = m.application;
      return [`${SAMPLE[i]}.png`, a.brand_name, a.class_type, a.alcohol_content, a.net_contents, a.producer_name_address,
        a.country_of_origin || "", a.is_import ? "yes" : "no", a.beverage_type, "yes"].map(q).join(",");
    }));
    batch.csvText = lines.join("\n");
    batch.csvName = "sample-batch.csv";
    batch.files = blobs.map((b, i) => new File([b], `${SAMPLE[i]}.png`, { type: "image/png" }));
    validateBatch();
  } catch {
    showError("The sample batch could not be loaded. Reload the page and try again.", "batch-error");
  }
});

// ---------------------------------------------------------------- batch: run
const ORDER = { fail: 0, error: 1, needs_review: 2, pass: 3, pending: 4, skipped: 5 };

function itemStatus(it) {
  if (it.skipped) return "skipped";
  if (it.error) return "error";
  if (it.result) return it.result.overall;
  return "pending";
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function checkItem(it, provider) {
  const body = new FormData();
  for (const f of it.images) body.append("image", f);
  body.append("application", JSON.stringify(it.app));
  body.append("provider", provider);
  body.append("all_sides", it.allSides ? "true" : "false");
  body.append("wait_for_cloud", "true");
  const started = performance.now();
  for (let attempt = 0; attempt < 6; attempt++) {
    if (batch.stop) return;
    let resp, data = null;
    try {
      resp = await fetch("api/verify", { method: "POST", body });
      try { data = await resp.json(); } catch { /* non-JSON */ }
    } catch {
      await sleep(2000 * (attempt + 1));
      continue; // network hiccup: try again
    }
    if (resp.ok) {
      it.result = data; it.error = null; it.seconds = (performance.now() - started) / 1000;
      return;
    }
    if (resp.status === 429 || resp.status === 503) {
      const wait = Number(resp.headers.get("Retry-After")) || 5;
      await sleep(Math.min(30, wait) * 1000);
      continue; // busy or over the rate limit: wait and retry, this is not the label's fault
    }
    it.error = (data && data.message) || `The server answered ${resp.status}.`;
    return;
  }
  it.error = "The server stayed busy; use Retry.";
}

async function runBatch(items) {
  const provider = $("batch-provider").value;
  batch.running = true; batch.stop = false;
  $("batch-start").disabled = true; $("batch-stop").hidden = false; $("batch-retry").hidden = true;
  $("batch-results").hidden = false; $("batch-detail").hidden = true;
  batch.started = performance.now();
  const queue = items.slice();
  const tick = setInterval(renderBatch, 500);
  const worker = async () => {
    while (queue.length && !batch.stop) {
      const it = queue.shift();
      it.running = true;
      await checkItem(it, provider);
      it.running = false;
      renderBatch();
    }
  };
  await Promise.all(Array.from({ length: BATCH_CONCURRENCY }, worker));
  clearInterval(tick);
  batch.running = false;
  batch.finished = performance.now();
  $("batch-stop").hidden = true;
  $("batch-start").disabled = false;
  $("batch-start").textContent = "Check all labels again";
  renderBatch();
}

$("batch-start").addEventListener("click", () => {
  for (const it of batch.items) { it.result = null; it.error = null; it.seconds = null; }
  batch.finished = null;
  runBatch(batch.items.filter((i) => !i.skipped));
});
$("batch-stop").addEventListener("click", () => { batch.stop = true; });
$("batch-retry").addEventListener("click", () => {
  const failed = batch.items.filter((i) => !i.skipped && (i.error || !i.result));
  for (const it of failed) it.error = null;
  batch.finished = null;
  runBatch(failed);
});

function problemsOf(it) {
  if (it.skipped) return it.skipped;
  if (it.error) return it.error;
  if (!it.result) return it.running ? "Checking…" : "Waiting";
  const bad = it.result.checks.filter((c) => c.status === "fail" || c.status === "needs_review");
  return bad.length ? bad.map((c) => `${FIELD_LABELS[c.field] || c.field}: ${STATUS[c.status].word}`).join("; ") : "—";
}

function renderBatch() {
  const all = batch.items;
  const runnable = all.filter((i) => !i.skipped);
  const done = runnable.filter((i) => i.result || i.error);
  const count = (s) => all.filter((i) => itemStatus(i) === s).length;
  $("batch-progress").max = runnable.length || 1;
  $("batch-progress").value = done.length;
  const elapsed = ((batch.finished || performance.now()) - batch.started) / 1000;
  $("batch-progress-text").textContent = `${done.length} of ${runnable.length} checked` +
    ` · ${elapsed >= 60 ? `${Math.floor(elapsed / 60)} min ${Math.round(elapsed % 60)} s` : `${elapsed.toFixed(0)} s`}` +
    (batch.running ? "" : batch.stop ? " · stopped" : " · finished");
  $("batch-counts").replaceChildren(
    ...["fail", "needs_review", "pass", "error"].map((s) => el("span", { class: "count" }, pill(s), ` ${count(s)}`)),
    count("skipped") ? el("span", { class: "count" }, `Skipped: ${count("skipped")}`) : "");
  const sorted = all.slice().sort((a, b) => (ORDER[itemStatus(a)] - ORDER[itemStatus(b)]) || (a.line - b.line));
  const tbody = $("batch-body");
  tbody.replaceChildren(...sorted.map((it) => {
    const st = itemStatus(it);
    const cell = ["pending", "skipped"].includes(st)
      ? el("span", { class: "muted" }, st === "skipped" ? "Skipped" : it.running ? "Checking…" : "Waiting")
      : pill(st);
    const name = it.result
      ? el("button", { type: "button", class: "link-button", "data-line": String(it.line) }, it.label)
      : it.label;
    return el("tr", {},
      el("td", { "data-label": "Result" }, cell),
      el("td", { "data-label": "Label" }, name),
      el("td", { "data-label": "Brand" }, it.app.brand_name || ""),
      el("td", { "data-label": "Needs attention" }, problemsOf(it)),
      el("td", { "data-label": "Time" }, it.seconds ? `${it.seconds.toFixed(1)} s` : ""));
  }));
  const failed = runnable.filter((i) => i.error || (!i.result && !batch.running));
  $("batch-retry").hidden = batch.running || !failed.length;
  $("batch-export").disabled = !done.length;
}

$("batch-body").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-line]");
  if (!btn) return;
  const it = batch.items.find((i) => String(i.line) === btn.dataset.line);
  const root = $("batch-detail");
  $("batch-detail-title").textContent = `${it.label} (row ${it.line})`;
  renderResult(root, it.result, it.seconds);
  root.hidden = false;
  $("batch-results").hidden = true;
  root.scrollIntoView({ behavior: "smooth", block: "start" });
  $("batch-detail-close").focus();
});
$("batch-detail-close").addEventListener("click", () => {
  $("batch-detail").hidden = true;
  $("batch-results").hidden = false;
});

$("batch-export").addEventListener("click", () => {
  const fields = Object.keys(FIELD_LABELS);
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = ["row", "filename", "brand_name", "overall", ...fields, "engine", "seconds", "reasons"];
  const lines = [head.join(",")];
  for (const it of batch.items.slice().sort((a, b) => a.line - b.line)) {
    const st = itemStatus(it);
    const r = it.result;
    const byField = r ? Object.fromEntries(r.checks.map((c) => [c.field, c.status])) : {};
    const reasons = r ? r.checks.filter((c) => c.status !== "pass" && c.status !== "n/a").map((c) => `${FIELD_LABELS[c.field]}: ${c.reason}`).join(" | ")
      : (it.skipped || it.error || "");
    lines.push([it.line, it.label, it.app.brand_name, st, ...fields.map((f) => byField[f] || ""),
      r ? (ENGINE_LABELS[r.provider] || r.provider) : "", it.seconds ? it.seconds.toFixed(1) : "", reasons].map(q).join(","));
  }
  const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv" }));
  const a = el("a", { href: url, download: "label-check-results.csv" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

loadConfig();
