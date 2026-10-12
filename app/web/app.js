"use strict";

const STATUS = {
  pass: { icon: "✔", word: "Pass" },
  needs_review: { icon: "⚠", word: "Needs review" },
  fail: { icon: "✖", word: "Fail" },
  "n/a": { icon: "–", word: "Not applicable" },
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

const $ = (id) => document.getElementById(id);
let currentFile = null;
let maxUploadMb = 10;

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

function showError(message) {
  const box = $("form-error");
  box.textContent = message;
  box.hidden = !message;
}

// ---- image selection ----
function setFile(file) {
  showError("");
  if (!file) return;
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    showError("That file type is not supported. Choose a JPEG, PNG or WebP image of the label.");
    return;
  }
  if (file.size > maxUploadMb * 1024 * 1024) {
    showError(`The image is larger than ${maxUploadMb} MB. Use a smaller photo.`);
    return;
  }
  currentFile = file;
  const preview = $("preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  $("drop-text").hidden = true;
  $("file-name").textContent = `Selected: ${file.name}`;
}

const dropZone = $("drop-zone");
$("image-input").addEventListener("change", (e) => setFile(e.target.files[0]));
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("image-input").click(); }
});
["dragenter", "dragover"].forEach((t) => dropZone.addEventListener(t, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((t) => dropZone.addEventListener(t, (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); }));
dropZone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

$("is_import").addEventListener("change", (e) => { $("country-field").hidden = !e.target.checked; });

// ---- examples ----
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
    setFile(new File([img], `${name}.png`, { type: "image/png" }));
    $("results").hidden = true;
  } catch {
    showError("The example could not be loaded. Reload the page and try again.");
  }
});

// ---- engines ----
async function loadConfig() {
  const select = $("provider");
  try {
    const cfg = await fetch("api/config").then((r) => r.json());
    maxUploadMb = cfg.max_upload_mb || 10;
    const options = [["local", "Offline OCR (works without internet)", cfg.providers.local]];
    options.unshift(["azure", "Cloud AI (checks bold type)", cfg.providers.azure]);
    for (const [value, label, enabled] of options) {
      const opt = el("option", { value }, enabled ? label : `${label} – not available`);
      if (!enabled) opt.disabled = true;
      select.append(opt);
    }
    select.value = cfg.providers.azure ? "azure" : "local";
    $("provider-note").textContent = cfg.providers.azure
      ? ""
      : "Offline OCR cannot see bold type, so a label that passes everything else shows “Needs review” for the warning.";
  } catch {
    select.append(el("option", { value: "local" }, "Offline OCR"));
  }
}

// ---- verify ----
$("verify-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  if (!currentFile) { showError("Please choose a label image first."); return; }
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
  if (missing.length) { showError(`Please fill in: ${missing.join(", ")}.`); return; }

  const body = new FormData();
  body.append("image", currentFile);
  body.append("application", JSON.stringify(app));
  body.append("provider", $("provider").value);

  const btn = $("verify-btn");
  btn.disabled = true;
  btn.textContent = "Checking label…";
  const started = performance.now();
  try {
    const resp = await fetch("api/verify", { method: "POST", body });
    let data = null;
    try { data = await resp.json(); } catch { /* non-JSON */ }
    if (!resp.ok) {
      showError((data && data.message) || "The label could not be checked. Please try again.");
      return;
    }
    renderResult(data, (performance.now() - started) / 1000);
  } catch {
    showError("Could not reach the server. Check your connection and try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Verify label";
  }
});

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

function renderResult(r, roundTripSeconds) {
  const s = STATUS[r.overall];
  const banner = $("banner");
  banner.className = `banner ${statusClass(r.overall)}`;
  banner.replaceChildren(
    el("span", { class: "icon", "aria-hidden": "true" }, s.icon),
    el("span", {}, s.word),
    el("span", { class: "time" },
      `Checked in ${roundTripSeconds.toFixed(1)} s (server ${(r.timings_ms.total / 1000).toFixed(1)} s) · Engine: ${ENGINE_LABELS[r.provider] || r.provider}`),
  );
  const msg = $("result-message");
  msg.textContent = r.message || "";
  msg.hidden = !r.message;

  const tbody = $("checks-body");
  tbody.replaceChildren();
  for (const c of r.checks) {
    const why = el("td", {}, c.reason);
    if (c.field === "government_warning" && c.details) {
      const det = el("details", { class: "diff" }, el("summary", {}, "Show warning details"));
      const steps = el("ul", { class: "steps" });
      for (const st of c.details.steps || []) {
        steps.append(el("li", {}, `${(STATUS[st.status] || {}).word || st.status} – ${st.step}: ${st.reason}`));
      }
      det.append(steps);
      if (c.details.diff && c.details.diff.length) {
        det.append(el("p", { class: "diff-legend" }, "Struck-through text is required but missing; underlined text is on the label but not in the required wording."));
        det.append(renderDiff(c.details.diff));
      }
      why.append(det);
    }
    tbody.append(el("tr", {},
      el("td", {}, pill(c.status)),
      el("th", { scope: "row" }, FIELD_LABELS[c.field] || c.field),
      el("td", { class: "expected" }, c.field === "government_warning" ? "Exact text required by 27 CFR 16.21" : (c.expected ?? "—")),
      el("td", { class: "found" }, c.found ?? "Not found"),
      why,
    ));
  }
  const list = $("not-checked-list");
  list.replaceChildren(...r.not_checked.map((t) => el("li", {}, t)));
  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

loadConfig();
