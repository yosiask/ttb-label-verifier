#!/usr/bin/env python3
"""Download the label images of the registry fixtures from TTB's Public COLA Registry, unchanged.

    pip install playwright && playwright install chromium
    python scripts/fetch_registry_images.py            # -> tests/fixtures/registry/images/

Read-only GETs of public pages, a few seconds apart (about 21 records). The registry sits behind a
JavaScript bot check, so a real browser engine (headless Chromium) loads the pages; it sends an
ordinary desktop browser user-agent because the check turns away the default "HeadlessChrome" one.
Bytes are saved exactly as served and their SHA-256 recorded in registry/SHA256SUMS (committed), so a rerun can
confirm the artwork is the same as when the expected results were written.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "tests" / "fixtures" / "registry"
IMAGES = DIR / "images"
BASE = "https://ttbonline.gov/colasonline/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def wanted() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for p in DIR.glob("*.json"):
        src = json.loads(p.read_text())["source"]
        out.setdefault(src["ttb_id"], set()).update(src["registry_images"])
    return out


def main() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    sums = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto(BASE + "publicSearchColasBasic.do", timeout=60000)
        page.wait_for_selector("#datecompletedfrom", timeout=30000)  # bot check passed
        for ttb_id, numbers in sorted(wanted().items()):
            time.sleep(3)
            page.goto(BASE + f"viewColaDetails.do?action=publicFormDisplay&ttbid={ttb_id}", timeout=60000)
            page.wait_for_load_state("networkidle")
            srcs = [s for s in (i.get_attribute("src") or "" for i in page.query_selector_all("img"))
                    if "publicViewAttachment" in s]
            for n in sorted(numbers):
                tab = ctx.new_page()
                r = tab.goto("https://ttbonline.gov" + srcs[n - 1], timeout=60000)
                body = r.body()
                tab.close()
                ext = r.headers.get("content-type", "image/jpeg").split("/")[-1].split(";")[0].replace("jpeg", "jpg")
                name = f"{ttb_id}_{n}.{ext}"
                (IMAGES / name).write_bytes(body)
                sums.append(f"{hashlib.sha256(body).hexdigest()}  {name}")
                print(name, len(body), "bytes", flush=True)
        browser.close()
    (DIR / "SHA256SUMS").write_text("\n".join(sorted(sums, key=lambda s: s.split()[1])) + "\n")


if __name__ == "__main__":
    main()
