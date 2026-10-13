#!/usr/bin/env python3
"""Measure accuracy and speed of a running instance on every fixture, per engine.

    python scripts/run_accuracy.py https://<app> --provider azure --provider local --reps 2 \\
        --report docs/validation-report.md

Measured, not simulated: each label goes through the real HTTP API of the given instance.
Ground truth comes from the fixture JSON, written by hand (scripts/make_fixtures.py,
scripts/make_photo_fixtures.py), never from the app's output:

  truth      compliant | violation | review   (photo fixtures state it; for the clean
             fixtures it is derived from the expected cloud verdict)
  false pass   a violation, or a label that should be reviewed, marked Pass
  false fail   a compliant label marked Fail
  detection    violations marked Fail
  review rate  Needs review among compliant + violation labels
  as expected  verdict and listed field statuses within the fixture's accepted answers

Cloud calls are spaced (--per-minute) to stay inside the app's cloud pace, so the
cloud is really used rather than the offline fallback; a fallback is reported, not hidden.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SETS = {"clean": ROOT / "tests" / "fixtures", "photos": ROOT / "tests" / "fixtures" / "photos"}
PRICE_IN, PRICE_OUT = 0.44, 1.76  # USD per million tokens, gpt-4.1-mini regional Standard (eastus2 list price)


def truth_of(meta: dict) -> str:
    if "truth" in meta:
        return meta["truth"]
    overall = meta["expected"]["azure_vision"]["overall"]
    if "pass" in overall:
        return "compliant"
    if "fail" in overall:
        return "violation"
    return "review"


def load(sets: list[str], only: list[str] | None) -> list[tuple[str, str, dict, Path]]:
    out = []
    for s in sets:
        for p in sorted(SETS[s].glob("*.json")):
            meta = json.loads(p.read_text())
            if not only or meta["case"] in only:
                out.append((s, meta["case"], meta, SETS[s]))
    return out


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def run_one(client: httpx.Client, base: str, meta: dict, folder: Path, provider: str) -> dict:
    images = meta.get("images") or [meta["image"]]
    files = [("image", (n, (folder / n).read_bytes(), "image/jpeg" if n.endswith(".jpg") else "image/png"))
             for n in images]
    data = {"application": json.dumps(meta["application"]), "provider": provider,
            "all_sides": "true" if meta.get("all_sides", False) else "false"}
    started = time.perf_counter()
    r = client.post(f"{base}/api/verify", files=files, data=data)
    rt = (time.perf_counter() - started) * 1000
    row = {"status": r.status_code, "round_trip_ms": round(rt), "images": len(images)}
    body = r.json()
    if r.status_code != 200:
        row["error"] = body
        return row
    engine = "azure_vision" if body["provider"] == "azure_vision" else "local_ocr"
    exp = meta["expected"][engine]
    fields = {c["field"]: c["status"] for c in body["checks"]}
    misses = {f: [fields.get(f), s] for f, s in exp.get("fields", {}).items()
              if fields.get(f) not in (s if isinstance(s, list) else [s])}
    row.update(engine=body["provider"], overall=body["overall"], allowed=exp["overall"],
               as_expected=body["overall"] in exp["overall"] and not misses, field_misses=misses, fields=fields,
               server_ms=body["timings_ms"]["total"], tokens=body.get("token_usage"), message=body.get("message"),
               reasons={c["field"]: c["reason"] for c in body["checks"] if c["status"] != "pass"})
    return row


def summarize(rows: list[dict]) -> dict:
    done = [r for r in rows if r["status"] == 200]
    by = lambda t: [r for r in done if r["truth"] == t]  # noqa: E731
    comp, viol, rev = by("compliant"), by("violation"), by("review")
    decided = comp + viol
    s = {
        "requests": len(rows), "answered": len(done), "errors": len(rows) - len(done),
        "fell_back_offline": sum(1 for r in done if r["requested"] == "azure" and r["engine"] != "azure_vision"),
        "compliant": len(comp), "violations": len(viol), "should_review": len(rev),
        "as_expected": sum(r["as_expected"] for r in done),
        "false_pass": sum(r["overall"] == "pass" for r in viol + rev),
        "false_fail": sum(r["overall"] == "fail" for r in comp),
        "detected": sum(r["overall"] == "fail" for r in viol),
        "flagged": sum(r["overall"] != "pass" for r in viol),
        "needs_review": sum(r["overall"] == "needs_review" for r in decided),
        "decided": len(decided),
    }
    if done:
        rt = [r["round_trip_ms"] for r in done]
        sv = [r["server_ms"] for r in done]
        s.update(rt_p50=pct(rt, .5), rt_p95=pct(rt, .95), rt_max=max(rt), srv_p50=pct(sv, .5), srv_p95=pct(sv, .95))
        single = [r["round_trip_ms"] for r in done if r["images"] == 1]
        if single:
            s.update(rt1_p50=pct(single, .5), rt1_p95=pct(single, .95))
    tok = [r["tokens"] for r in done if r.get("tokens")]
    if tok:
        pin = sum(t["prompt_tokens"] for t in tok)
        pout = sum(t["completion_tokens"] for t in tok)
        s.update(token_rows=len(tok), prompt_tokens=pin, completion_tokens=pout,
                 usd=round((pin * PRICE_IN + pout * PRICE_OUT) / 1e6, 4),
                 usd_per_label=round((pin * PRICE_IN + pout * PRICE_OUT) / 1e6 / len(tok), 5))
    return s


def rate(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def report(results: dict, args, started: str) -> str:
    lines = [
        "# Validation report",
        "",
        f"**Measured** on {args.base_url} ({started} UTC) by `scripts/run_accuracy.py`: every fixture through the "
        f"real HTTP API, {args.reps} repetition(s) per engine. Round trips include the internet path from the test "
        "machine (a VPS outside Azure) to the app.",
        "",
        "Fixtures are synthetic: `clean` are flat rendered labels; `photos` are simulated photographs (curvature, "
        "angle, glare, blur, small text, unusual fonts, front/back labels). They are not real photos of real "
        "products. Ground truth is hand-written in the generators.",
        "",
        "| Engine | Set | Labels | As expected | False pass | False fail | Detection (Fail) | Flagged (not Pass) "
        "| Needs review | p50 / p95 round trip | Server p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (prov, st), s in results.items():
        lines.append(
            f"| {prov} | {st} | {s['answered']} | {rate(s['as_expected'], s['answered'])} | "
            f"{rate(s['false_pass'], s['violations'] + s['should_review'])} | {rate(s['false_fail'], s['compliant'])} | "
            f"{rate(s['detected'], s['violations'])} | {rate(s['flagged'], s['violations'])} | "
            f"{rate(s['needs_review'], s['decided'])} | {s.get('rt_p50', 0) / 1000:.1f} s / {s.get('rt_p95', 0) / 1000:.1f} s | "
            f"{s.get('srv_p50', 0) / 1000:.1f} s / {s.get('srv_p95', 0) / 1000:.1f} s |")
    lines += ["", "False pass counts violations *and* labels whose right answer is Needs review. "
              "Needs review is over labels whose right answer is Pass or Fail.", ""]
    for (prov, st), s in results.items():
        extra = []
        if s.get("fell_back_offline"):
            extra.append(f"{s['fell_back_offline']} cloud requests fell back to offline OCR")
        if s.get("errors"):
            extra.append(f"{s['errors']} errors")
        if s.get("usd") is not None:
            extra.append(f"tokens: {s['prompt_tokens']:,} in / {s['completion_tokens']:,} out over {s['token_rows']} "
                         f"labels = ${s['usd']:.3f} (${s['usd_per_label']:.4f} per label at list price)")
        if extra:
            lines.append(f"- {prov} / {st}: " + "; ".join(extra) + ".")
    lines += ["", "## Per label", "", "| Engine | Set | Label | Truth | Verdicts | Accepted | Notes |", "|---|---|---|---|---|---|---|"]
    per: dict = {}
    for r in args.rows:
        if r["status"] != 200:
            continue
        per.setdefault((r["requested"], r["set"], r["case"]), []).append(r)
    for (prov, st, case), rs in sorted(per.items()):
        verdicts = ", ".join(r["overall"] for r in rs)
        notes = "; ".join(sorted({f"{k}: {v}" for r in rs for k, v in r["field_misses"].items()}))
        flag = " **FALSE PASS**" if any(r["overall"] == "pass" and r["truth"] != "compliant" for r in rs) else ""
        flag += " **FALSE FAIL**" if any(r["overall"] == "fail" and r["truth"] == "compliant" for r in rs) else ""
        lines.append(f"| {prov} | {st} | {case} | {rs[0]['truth']} | {verdicts}{flag} | {'/'.join(rs[0]['allowed'])} | {notes} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--provider", action="append", choices=["azure", "local", "auto"])
    ap.add_argument("--set", action="append", choices=list(SETS))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--per-minute", type=float, default=12, help="pace for cloud requests")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default="accuracy_rows.jsonl")
    ap.add_argument("--report")
    a = ap.parse_args()
    providers = a.provider or ["azure", "local"]
    sets = a.set or list(SETS)
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    cases = load(sets, a.only)
    a.rows = []
    with httpx.Client(timeout=90) as client, open(a.out, "w") as out:
        for prov in providers:
            gap = 60.0 / a.per_minute if prov != "local" else 0.0
            for rep in range(a.reps):
                for st, case, meta, folder in cases:
                    t0 = time.perf_counter()
                    row = run_one(client, a.base_url.rstrip("/"), meta, folder, prov)
                    row.update(requested=prov, set=st, case=case, rep=rep, truth=truth_of(meta))
                    a.rows.append(row)
                    out.write(json.dumps(row) + "\n")
                    mark = "ok " if row.get("as_expected") else ("ERR" if row["status"] != 200 else "-- ")
                    if row.get("overall") == "pass" and row["truth"] != "compliant":
                        mark = "FP!"
                    print(f"{mark} {prov:5s} {st:6s} {case:30s} {row['truth']:9s} {row.get('overall', row['status'])!s:12s} "
                          f"{row['round_trip_ms']:6d} ms {row.get('field_misses') or ''}", flush=True)
                    time.sleep(max(0.0, gap * row["images"] - (time.perf_counter() - t0)))
    results = {}
    for prov in providers:
        for st in sets:
            rs = [r for r in a.rows if r["requested"] == prov and r["set"] == st]
            if rs:
                results[(prov, st)] = summarize(rs)
    for k, s in results.items():
        print(k, json.dumps(s))
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(report(results, a, started))
        print(f"wrote {a.report}")


if __name__ == "__main__":
    main()
