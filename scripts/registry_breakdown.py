#!/usr/bin/env python3
"""Break down registry results (rows written by run_accuracy.py --out) by kind of case, and list
field-level misses on every set: a field the fixture says must not pass (e.g. a misspelled class
statement) that passed. The label can still be Needs review or Fail overall because of another field,
so these are not overall false passes, but they are a reader or rule missing what it should catch.

    python scripts/registry_breakdown.py accuracy_rows.jsonl >> docs/validation-report.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "tests" / "fixtures" / "registry"
SETS = {"clean": ROOT / "tests" / "fixtures", "photos": ROOT / "tests" / "fixtures" / "photos", "registry": REG}
KINDS = {"as_filed": "As filed (approved artwork, every image)",
         "front_only": "Front or display panel only, 'every side' not ticked",
         "altered_application": "Untouched artwork, one application field wrong"}


def main(path: str) -> None:
    meta = {p.stem: json.loads(p.read_text()) for p in REG.glob("*.json")}
    rows = [r for r in map(json.loads, open(path)) if r.get("set") == "registry" and r["status"] == 200]
    errors = sum(1 for r in map(json.loads, open(path)) if r.get("set") == "registry" and r["status"] != 200)
    out = ["", "## Authentic registry labels: by kind of case", "",
           "| Engine | Kind | Checks | Pass | Needs review | Fail | False pass | False fail |", "|---|---|---|---|---|---|---|---|"]
    by = defaultdict(list)
    for r in rows:
        by[(r["requested"], meta[r["case"]]["kind"])].append(r)
    for (prov, kind), rs in sorted(by.items()):
        n = len(rs)
        cnt = {o: sum(r["overall"] == o for r in rs) for o in ("pass", "needs_review", "fail")}
        fp = sum(r["overall"] == "pass" and r["truth"] != "compliant" for r in rs)
        ff = sum(r["overall"] == "fail" and r["truth"] == "compliant" for r in rs)
        out.append(f"| {prov} | {KINDS[kind]} | {n} | {cnt['pass']} | {cnt['needs_review']} | {cnt['fail']} | {fp} | {ff} |")
    out += ["", "Front-only cases are Needs review by design; a Fail there means something visible on the front "
            "panel was judged wrong.", ""]
    allmeta = {(st, p.stem): json.loads(p.read_text()) for st, d in SETS.items() for p in d.glob("*.json")}
    every = [r for r in map(json.loads, open(path)) if r["status"] == 200]
    fps = defaultdict(list)
    for r in every:
        m = allmeta[(r["set"], r["case"])]
        engine = "azure_vision" if r["engine"] == "azure_vision" else "local_ocr"
        for field, allowed in m["expected"][engine].get("fields", {}).items():
            allowed = allowed if isinstance(allowed, list) else [allowed]
            if "pass" not in allowed and r["fields"].get(field) == "pass":
                fps[(r["requested"], r["set"], r["case"], field)].append(r["overall"])
    out.append("## Field-level misses (all sets)")
    out.append("")
    out.append("A field that must not pass, passed. The label's overall verdict is in brackets; an overall "
               "false pass would also appear in the summary table.")
    out.append("")
    if not fps:
        out.append("- none")
    for (prov, st, case, field), overall in sorted(fps.items()):
        total = sum(1 for r in every if r["case"] == case and r["set"] == st and r["requested"] == prov)
        out.append(f"- {prov} / {st} / {case} / {field}: {len(overall)} of {total} runs (overall: "
                   f"{', '.join(overall)}). {allmeta[(st, case)].get('description', '')}")
    if errors:
        out += ["", f"{errors} registry requests returned an error (counted in the summary above)."]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
