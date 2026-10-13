#!/usr/bin/env python3
"""Break down registry results (rows written by run_accuracy.py --out) by kind of case, and list
field-level false passes: a field the truth says must not pass (e.g. the misspelled class statement)
that passed, even when the label's overall verdict was not Pass.

    python scripts/registry_breakdown.py accuracy_rows.jsonl >> docs/validation-report.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "tests" / "fixtures" / "registry"
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
    fps = defaultdict(list)
    for r in rows:
        for field, allowed in meta[r["case"]]["expected"]["azure_vision"]["fields"].items():
            allowed = allowed if isinstance(allowed, list) else [allowed]
            if "pass" not in allowed and r["fields"].get(field) == "pass":
                fps[(r["requested"], r["case"], field)].append(r["overall"])
    out.append("**Field-level false passes** (a field that must not pass, passed; the label's overall verdict "
               "in brackets):")
    out.append("")
    if not fps:
        out.append("- none")
    for (prov, case, field), overall in sorted(fps.items()):
        out.append(f"- {prov} / {case} / {field}: {len(overall)} of {sum(1 for r in rows if r['case'] == case and r['requested'] == prov)} "
                   f"runs (overall: {', '.join(overall)}). {meta[case]['description']}")
    if errors:
        out += ["", f"{errors} registry requests returned an error (counted in the summary above)."]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
