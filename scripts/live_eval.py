#!/usr/bin/env python3
"""Run the fixture set against a running instance and score it (measured, not simulated).

    python scripts/live_eval.py https://<app>.azurecontainerapps.io --provider azure --reps 2

Each fixture's JSON holds the hand-written expected result per engine. A result is:
  false pass   overall Pass although the fixture expects a Fail or Needs review
  false fail   overall Fail although the fixture does not allow Fail
  field miss   a field's status differs from the expected one
Calls are spaced (--per-minute) to stay inside the app's cloud pace, so the cloud
is really used rather than the offline fallback. Results go to --out as JSON lines.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import time
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--provider", default="azure", choices=["azure", "auto", "local"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--per-minute", type=float, default=10)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default="live_eval.jsonl")
    a = ap.parse_args()

    metas = []
    for p in sorted(glob.glob(str(FIXTURES / "*.json"))):
        name = os.path.basename(p)[:-5]
        if not a.only or name in a.only:
            metas.append((name, json.load(open(p))))

    rows = []
    gap = 60.0 / a.per_minute
    with httpx.Client(timeout=60) as client, open(a.out, "a") as out:
        for rep in range(a.reps):
            for name, meta in metas:
                started = time.perf_counter()
                img = meta["image"]
                ctype = "image/jpeg" if img.endswith(".jpg") else "image/png"
                r = client.post(f"{a.base_url}/api/verify",
                                files={"image": (img, (FIXTURES / img).read_bytes(), ctype)},
                                data={"application": json.dumps(meta["application"]), "provider": a.provider})
                rt_ms = (time.perf_counter() - started) * 1000
                body = r.json()
                row = {"fixture": name, "rep": rep, "status": r.status_code, "round_trip_ms": round(rt_ms)}
                if r.status_code == 200:
                    engine = "azure_vision" if body["provider"] == "azure_vision" else "local_ocr"
                    exp = meta["expected"][engine]
                    fields = {c["field"]: c["status"] for c in body["checks"]}
                    misses = {f: (fields.get(f), s) for f, s in exp.get("fields", {}).items()
                              if fields.get(f) not in (s if isinstance(s, list) else [s])}
                    row.update(
                        engine=body["provider"], overall=body["overall"], allowed=exp["overall"],
                        ok=body["overall"] in exp["overall"] and not misses,
                        false_pass=body["overall"] == "pass" and "pass" not in exp["overall"],
                        false_fail=body["overall"] == "fail" and "fail" not in exp["overall"],
                        field_misses=misses, fields=fields, timings=body["timings_ms"], message=body.get("message"),
                        warning=next((c for c in body["checks"] if c["field"] == "government_warning"), {}).get("reason"),
                    )
                else:
                    row.update(error=body)
                rows.append(row)
                out.write(json.dumps(row) + "\n")
                flag = "OK " if row.get("ok") else "ERR" if r.status_code != 200 else "MISS"
                print(f"{flag} {name:24s} {row.get('engine', r.status_code)!s:12s} {row.get('overall', '')!s:12s} "
                      f"allowed={row.get('allowed')} {rt_ms:6.0f} ms {row.get('field_misses') or ''}", flush=True)
                time.sleep(max(0.0, gap - (time.perf_counter() - started)))

    done = [r for r in rows if r["status"] == 200]
    cloud = [r for r in done if r["engine"] == "azure_vision"]
    print(f"\nrequests={len(rows)} answered={len(done)} cloud={len(cloud)} errors={len(rows) - len(done)}")
    if done:
        print(f"as expected={sum(r['ok'] for r in done)}  false_pass={sum(r['false_pass'] for r in done)}  "
              f"false_fail={sum(r['false_fail'] for r in done)}  "
              f"needs_review={sum(r['overall'] == 'needs_review' for r in done)}")
        rt = [r["round_trip_ms"] for r in done]
        srv = [r["timings"]["total"] for r in done]
        ext = [r["timings"].get("extract", 0) for r in done]
        print(f"round trip p50={pct(rt, .5):.0f} p95={pct(rt, .95):.0f} max={max(rt):.0f} ms | "
              f"server p50={pct(srv, .5):.0f} p95={pct(srv, .95):.0f} | extract mean={statistics.mean(ext):.0f} ms")


if __name__ == "__main__":
    main()
