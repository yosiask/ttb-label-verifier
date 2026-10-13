"""Render synthetic labels with known ground truth.

Every expected result below is written by hand from what is rendered, never from
the app's output. Output: tests/fixtures/<case>.png + <case>.json, and a few
examples copied to app/web/examples/ for the UI's "Load example" button.

Run: python scripts/make_fixtures.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "app" / "web" / "examples"
sys.path.insert(0, str(ROOT))
from app.core.warning import CANONICAL_WARNING  # noqa: E402

FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation")]
REGULAR = "DejaVuSans.ttf"
BOLD = "DejaVuSans-Bold.ttf"
SERIF_BOLD = "DejaVuSerif-Bold.ttf"

W, H = 1100, 1500
BG = (250, 246, 236)
INK = (25, 25, 25)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        p = d / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise SystemExit(f"Font {name} not found; install fonts-dejavu-core.")


BASE_LABEL = {
    "brand": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol": "45% Alc./Vol. (90 Proof)",
    "net": "750 mL",
    "producer": "Distilled and Bottled by Old Tom Distillery, Bardstown, Kentucky",
    "country": None,
    "warning": CANONICAL_WARNING,
    "heading_bold": True,
    "body_bold": False,
}
BASE_APP = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "producer_name_address": "Old Tom Distillery, Bardstown, Kentucky",
    "country_of_origin": None,
    "is_import": False,
    "beverage_type": "spirits",
}
ALL_PASS = {f: "pass" for f in ("brand_name", "class_type", "alcohol_content", "net_contents", "producer_name_address")}


def wrap(draw: ImageDraw.ImageDraw, words: list[tuple[str, ImageFont.FreeTypeFont]], width: int):
    """Greedy word wrap of (word, font) pairs into lines."""
    lines, line, x = [], [], 0
    for word, f in words:
        w = draw.textlength(word + " ", font=f)
        if line and x + w > width:
            lines.append(line)
            line, x = [], 0
        line.append((word, f))
        x += w
    if line:
        lines.append(line)
    return lines


def render(label: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([30, 30, W - 30, H - 30], outline=(120, 90, 40), width=6)
    y = 110

    def centered(text: str, f: ImageFont.FreeTypeFont, gap: int):
        nonlocal y
        for line in wrap(d, [(w, f) for w in text.split()], W - 200):
            s = " ".join(w for w, _ in line)
            tw = d.textlength(s, font=f)
            d.text(((W - tw) / 2, y), s, font=f, fill=INK)
            y += int(f.size * 1.3)
        y += gap

    centered(label["brand"], font(SERIF_BOLD, 76), 30)
    centered(label["class_type"], font(REGULAR, 42), 50)
    centered(label["alcohol"], font(REGULAR, 40), 20)
    centered(label["net"], font(REGULAR, 40), 60)
    centered(label["producer"], font(REGULAR, 30), 20)
    if label.get("country"):
        centered(label["country"], font(REGULAR, 30), 20)

    if label.get("warning"):
        y = max(y + 40, 900)
        size = 26
        bold, reg = font(BOLD, size), font(BOLD if label["body_bold"] else REGULAR, size)
        heading_words = 2
        words = label["warning"].split()
        styled = [(w, (bold if label["heading_bold"] else reg) if i < heading_words else reg) for i, w in enumerate(words)]
        for line in wrap(d, styled, W - 200):
            x = 100
            for word, f in line:
                d.text((x, y), word, font=f, fill=INK)
                x += d.textlength(word + " ", font=f)
            y += int(size * 1.45)
    return img


def tilt(img: Image.Image, deg: float) -> Image.Image:
    return img.rotate(deg, expand=True, fillcolor=(200, 200, 200), resample=Image.BICUBIC)


def dim(img: Image.Image) -> Image.Image:
    img = ImageEnhance.Brightness(img).enhance(0.45)
    return ImageEnhance.Contrast(img).enhance(0.6)


def glare(img: Image.Image) -> Image.Image:
    a = np.asarray(img).astype(np.float32)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    blob = np.exp(-(((xx - w * 0.7) / (w * 0.22)) ** 2 + ((yy - h * 0.3) / (h * 0.12)) ** 2))
    a = a + (255 - a) * (0.75 * blob)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def low_res(img: Image.Image) -> Image.Image:
    return img.resize((img.width * 45 // 100, img.height * 45 // 100), Image.BILINEAR)


def blur(img: Image.Image, radius: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def blank(_: Image.Image) -> Image.Image:
    rng = np.random.default_rng(7)
    a = np.full((H, W, 3), 128, np.float32) + rng.normal(0, 40, (H, W, 3))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))


def case(name, description, label=None, app=None, local=None, vision=None, post=None, example=False):
    lab = copy.deepcopy(BASE_LABEL)
    lab.update(label or {})
    ap = copy.deepcopy(BASE_APP)
    ap.update(app or {})
    return {"case": name, "description": description, "label": lab, "application": ap,
            "expected": {"local_ocr": local, "azure_vision": vision}, "post": post, "example": example}


def exp(overall, fields=None):
    """overall: one status or a list of acceptable statuses."""
    return {"overall": overall if isinstance(overall, list) else [overall], "fields": fields or {}}


# Local OCR cannot see bold, so a label whose other checks pass is Needs review (by design).
BOLD_REVIEW = {"government_warning": "needs_review"}
CASES = [
    case("clean_spirits", "Compliant bourbon label (the brief's OLD TOM DISTILLERY example).",
         local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}), vision=exp("pass", ALL_PASS), example=True),
    case("brand_case_diff", "Label says STONE'S THROW, application says Stone's Throw: cosmetic only.",
         label={"brand": "STONE'S THROW", "producer": "Distilled and Bottled by Riverside Spirits Co., Portland, Oregon"},
         app={"brand_name": "Stone's Throw", "producer_name_address": "Riverside Spirits Co., Portland, Oregon"},
         local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}), vision=exp("pass", ALL_PASS), example=True),
    case("brand_wrong", "Label brand differs from the application.",
         label={"brand": "MAPLE CREEK", "producer": "Distilled and Bottled by Harbor Spirits Co., Louisville, Kentucky"},
         app={"brand_name": "BLUE HERON", "producer_name_address": "Harbor Spirits Co., Louisville, Kentucky"},
         local=exp("fail", {"brand_name": "fail"}), vision=exp("fail", {"brand_name": "fail"})),
    case("abv_mismatch", "Label 40% / 80 Proof, application 45%.",
         label={"alcohol": "40% Alc./Vol. (80 Proof)"},
         local=exp("fail", {"alcohol_content": "fail"}), vision=exp("fail", {"alcohol_content": "fail"}), example=True),
    case("proof_inconsistent", "Label 45% with 80 Proof: proof is not 2 x ABV.",
         label={"alcohol": "45% Alc./Vol. (80 Proof)"}, app={"alcohol_content": "45%"},
         local=exp("fail", {"alcohol_content": "fail"}), vision=exp("fail", {"alcohol_content": "fail"})),
    case("net_contents_units", "Label 75 cL, application 750 mL: same volume.",
         label={"net": "75 cL"},
         local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}), vision=exp("pass", ALL_PASS)),
    case("warning_title_case", "Warning heading in title case: \"Government Warning:\".",
         label={"warning": CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")},
         local=exp("fail", {"government_warning": "fail"}), vision=exp("fail", {"government_warning": "fail"}),
         example=True),
    case("warning_missing_colon", "Warning heading without the colon.",
         label={"warning": CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING")},
         local=exp("fail", {"government_warning": "fail"}), vision=exp("fail", {"government_warning": "fail"})),
    case("warning_altered_word", "Warning says \"may cause serious health problems\".",
         label={"warning": CANONICAL_WARNING.replace("cause health", "cause serious health")},
         local=exp("fail", {"government_warning": "fail"}), vision=exp("fail", {"government_warning": "fail"})),
    case("warning_missing", "No government warning on the label.",
         label={"warning": None},
         local=exp("fail", {"government_warning": "fail"}), vision=exp("fail", {"government_warning": "fail"})),
    case("warning_body_bold", "Whole warning in bold; the body must not be bold. Only the vision engine can see this.",
         label={"body_bold": True},
         local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}), vision=exp("fail", {"government_warning": "fail"})),
    case("warning_heading_not_bold", "Warning heading printed in regular type; it must be bold. Only the vision "
         "engine can see this. Guards against a reader that always reports the heading as bold. Live, the model "
         "answers \"can't tell\" (or, 1 run in 5, \"bold\"); the pixel weight check makes that Needs review.",
         label={"heading_bold": False},
         local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}),
         vision=exp(["fail", "needs_review"], {"government_warning": ["fail", "needs_review"]})),
    case("brand_only_in_address", "Application brand appears only inside the producer line.",
         label={"brand": "RIVER BEND", "producer": "Bottled by Stone's Throw Distillery, Frankfort, Kentucky"},
         app={"brand_name": "STONE'S THROW", "producer_name_address": "Stone's Throw Distillery, Frankfort, Kentucky"},
         local=exp("needs_review", {"brand_name": "needs_review"}),
         vision=exp(["needs_review", "fail"], {"brand_name": ["needs_review", "fail"]})),
    case("import_no_country", "Imported whisky with no country of origin on the label.",
         label={"brand": "GLEN ARDOCH", "class_type": "Blended Scotch Whisky", "alcohol": "40% Alc./Vol.",
                "producer": "Imported by Highland Imports Ltd., New York, NY"},
         app={"brand_name": "GLEN ARDOCH", "class_type": "Blended Scotch Whisky", "alcohol_content": "40%",
              "producer_name_address": "Highland Imports Ltd., New York, NY", "country_of_origin": "Scotland",
              "is_import": True},
         local=exp("fail", {"country_of_origin": "fail"}), vision=exp("fail", {"country_of_origin": "fail"})),
    case("import_country_ok", "Imported whisky with \"Product of Scotland\".",
         label={"brand": "GLEN ARDOCH", "class_type": "Blended Scotch Whisky", "alcohol": "40% Alc./Vol.",
                "producer": "Imported by Highland Imports Ltd., New York, NY", "country": "Product of Scotland"},
         app={"brand_name": "GLEN ARDOCH", "class_type": "Blended Scotch Whisky", "alcohol_content": "40%",
              "producer_name_address": "Highland Imports Ltd., New York, NY", "country_of_origin": "Scotland",
              "is_import": True},
         local=exp("needs_review", {**ALL_PASS, "country_of_origin": "pass", **BOLD_REVIEW}),
         vision=exp("pass", {**ALL_PASS, "country_of_origin": "pass"})),
    case("tilted_10deg", "Compliant label photographed 10 degrees off level.", post=("tilt", 10),
         local=exp("needs_review"), vision=exp(["pass", "needs_review"])),
    case("dim", "Compliant label, underexposed.", post=("dim",),
         local=exp("needs_review"), vision=exp(["pass", "needs_review"])),
    case("glare", "Compliant label with a glare patch.", post=("glare",),
         local=exp("needs_review"), vision=exp(["pass", "needs_review"])),
    case("low_res", "Compliant label at low resolution (495 x 675).", post=("low_res",),
         local=exp("needs_review"), vision=exp(["pass", "needs_review"])),
    case("abv_mismatch_tilted", "Violation on a degraded image: 40% label, 45% application, 6 degree tilt.",
         label={"alcohol": "40% Alc./Vol. (80 Proof)"}, post=("tilt", -6),
         local=exp(["fail", "needs_review"]), vision=exp(["fail", "needs_review"])),
    case("blank_or_unreadable", "No readable label: noise only.", post=("blank",),
         local=exp("needs_review"), vision=exp("needs_review")),
    case("brand_one_letter_off", "Label says MAPLE CREAK, application says MAPLE CREEK: a spelling difference "
         "that must not pass automatically.",
         label={"brand": "MAPLE CREAK", "producer": "Distilled and Bottled by Harbor Spirits Co., Louisville, Kentucky"},
         app={"brand_name": "MAPLE CREEK", "producer_name_address": "Harbor Spirits Co., Louisville, Kentucky"},
         local=exp("needs_review", {"brand_name": "needs_review"}),
         vision=exp("needs_review", {"brand_name": "needs_review"}), example=True),
    case("blurry", "Compliant label, out of focus.", post=("blur", 2.2),
         local=exp("needs_review"), vision=exp(["pass", "needs_review"])),
    case("exif_rotated", "Compliant label saved sideways as a phone JPEG with an EXIF rotation tag.",
         post=("exif",), local=exp("needs_review", {**ALL_PASS, **BOLD_REVIEW}), vision=exp("pass", ALL_PASS)),
]

POST = {"tilt": tilt, "dim": dim, "glare": glare, "low_res": low_res, "blank": blank, "blur": blur}


def save_exif_rotated(img: Image.Image, path: Path) -> None:
    """Store the pixels rotated 90 degrees with EXIF Orientation=6, as many phones do."""
    exif = Image.Exif()
    exif[0x0112] = 6  # display needs a 90 degree clockwise turn
    img.rotate(90, expand=True).save(path, "JPEG", quality=92, exif=exif)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for c in CASES:
        img = render(c["label"])
        image_name = f"{c['case']}.png"
        if c["post"] and c["post"][0] == "exif":
            image_name = f"{c['case']}.jpg"
            save_exif_rotated(img, OUT / image_name)
        else:
            if c["post"]:
                fn, *args = c["post"]
                img = POST[fn](img, *args)
            img.save(OUT / image_name, optimize=True)
        meta = {k: v for k, v in c.items() if k not in ("post", "example")}
        meta["image"] = image_name
        meta["degradation"] = list(c["post"]) if c["post"] else None
        (OUT / f"{c['case']}.json").write_text(json.dumps(meta, indent=2) + "\n")
        if c["example"]:
            shutil.copy(OUT / f"{c['case']}.png", EXAMPLES / f"{c['case']}.png")
            (EXAMPLES / f"{c['case']}.json").write_text(
                json.dumps({"description": c["description"], "application": c["application"]}, indent=2) + "\n")
    print(f"Wrote {len(CASES)} fixtures to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
