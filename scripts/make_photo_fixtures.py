"""Render realistic-looking label *photographs* with known ground truth.

Simulated, not real photos: each label design is rendered, wrapped around a bottle
(cylindrical curvature with shading), photographed at an angle, with glare, blur, sensor
noise and JPEG compression. Some labels are split into front and back panels, as on real
bottles. Ground truth is written by hand here, never from the app's output.

Each case states its truth:
  compliant   the label matches the application and the warning is correct
  violation   at least one real discrepancy (the expected verdict is Fail)
  review      the right answer is Needs review (e.g. a one-letter brand difference, or only
              the front label supplied, so a missing warning is not proof of a violation)

Output: tests/fixtures/photos/<case>[_front|_back].jpg + <case>.json
Run: python scripts/make_photo_fixtures.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "photos"
FONTS = ROOT / "scripts" / "fonts"
SYS_FONTS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation")]
sys.path.insert(0, str(ROOT))
from app.core.warning import CANONICAL_WARNING  # noqa: E402

BODY = CANONICAL_WARNING[len("GOVERNMENT WARNING: "):]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for d in [FONTS, *SYS_FONTS]:
        if (d / name).exists():
            return ImageFont.truetype(str(d / name), size)
    raise SystemExit(f"font {name} not found")


# ---------------------------------------------------------------- label design

@dataclass
class Design:
    bg: tuple = (246, 240, 225)
    ink: tuple = (30, 25, 20)
    accent: tuple = (130, 30, 30)
    brand_font: str = "OldStandard-Bold.ttf"
    brand_size: int = 84
    text_font: str = "OldStandard-Regular.ttf"
    warn_regular: str = "PT_Sans-Narrow-Web-Regular.ttf"
    warn_bold: str = "PT_Sans-Narrow-Web-Bold.ttf"
    warn_size: int = 19
    border: bool = True


@dataclass
class Label:
    brand: str = "OLD TOM DISTILLERY"
    class_type: str = "Kentucky Straight Bourbon Whiskey"
    alcohol: str = "45% Alc./Vol. (90 Proof)"
    net: str = "750 mL"
    producer: str = "Distilled and Bottled by Old Tom Distillery, Bardstown, Kentucky"
    country: str | None = None
    heading: str = "GOVERNMENT WARNING:"
    body: str = BODY
    heading_bold: bool = True
    body_bold: bool = False
    warning: bool = True


def _wrap(d, words, width):
    lines, line, x = [], [], 0.0
    for w, f in words:
        wl = d.textlength(w + " ", font=f)
        if line and x + wl > width:
            lines.append(line)
            line, x = [], 0.0
        line.append((w, f))
        x += wl
    return lines + ([line] if line else [])


def render_panel(lab: Label, des: Design, part: str = "full", size=(1000, 1300)) -> Image.Image:
    """part: full (everything), front (brand, type, ABV, net), back (producer, country, warning)."""
    W, H = size
    img = Image.new("RGB", size, des.bg)
    d = ImageDraw.Draw(img)
    if des.border:
        d.rectangle([22, 22, W - 22, H - 22], outline=des.accent, width=5)
        d.rectangle([36, 36, W - 36, H - 36], outline=des.accent, width=1)
    y = 90 if part != "back" else 110

    def centered(text, f, gap, color=None):
        nonlocal y
        for line in _wrap(d, [(w, f) for w in text.split()], W - 160):
            s = " ".join(w for w, _ in line)
            d.text(((W - d.textlength(s, font=f)) / 2, y), s, font=f, fill=color or des.ink)
            y += int(f.size * 1.28)
        y += gap

    if part in ("full", "front"):
        centered(lab.brand, font(des.brand_font, des.brand_size), 34, des.accent)
        centered(lab.class_type, font(des.text_font, 40), 40)
        if part == "front":
            y = max(y, int(H * 0.62))
        centered(lab.alcohol, font(des.text_font, 36), 18)
        centered(lab.net, font(des.text_font, 36), 40)
    if part in ("full", "back"):
        centered(lab.producer, font(des.text_font, 26), 14)
        if lab.country:
            centered(lab.country, font(des.text_font, 28), 14)
        if lab.warning:
            y = max(y + 30, int(H * (0.62 if part == "full" else 0.45)))
            fh = font(des.warn_bold if lab.heading_bold else des.warn_regular, des.warn_size)
            fb = font(des.warn_bold if lab.body_bold else des.warn_regular, des.warn_size)
            words = [(w, fh) for w in lab.heading.split()] + [(w, fb) for w in lab.body.split()]
            for line in _wrap(d, words, W - 200):
                x = 100
                for w, f in line:
                    d.text((x, y), w, font=f, fill=des.ink)
                    x += d.textlength(w + " ", font=f)
                y += int(des.warn_size * 1.4)
    if part == "back" and not lab.warning:
        centered("Enjoy responsibly.", font(des.text_font, 28), 10)
    return img


# ---------------------------------------------------------------- photography

@dataclass
class Shot:
    curve: float = 1.4  # radians of the bottle's circumference covered by the label (0 = flat)
    angle: float = 0.0  # in-plane rotation, degrees
    tilt: float = 0.0  # perspective: 0..0.15
    glare: tuple | None = None  # (x, y, rx, ry, strength) in label fractions
    blur: float = 0.8
    noise: float = 5.0
    jpeg: int = 82
    out_long: int = 1800  # long edge of the final photo
    glass: tuple = (70, 40, 15)  # bottle color around the label
    scene: tuple = (60, 60, 64)
    seed: int = 0


def wrap_cylinder(label: np.ndarray, theta: float) -> np.ndarray:
    """Project a flat label onto a cylinder seen head-on: compress toward the edges, shade."""
    h, w = label.shape[:2]
    if theta <= 0.01:
        return label
    r = w / theta  # label arc length = w
    out_w = int(round(2 * r * np.sin(theta / 2)))
    xs = (np.arange(out_w) - out_w / 2) / r  # sin(phi)
    phi = np.arcsin(np.clip(xs, -1, 1))
    src_x = (phi * r + w / 2).astype(np.float32)
    map_x = np.tile(src_x, (h, 1))
    map_y = np.tile(np.arange(h, dtype=np.float32)[:, None], (1, out_w))
    warped = cv2.remap(label, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    shade = (0.55 + 0.45 * np.cos(phi)) ** 0.8
    stripe = 1 + 0.18 * np.exp(-((phi + 0.35) ** 2) / 0.01)  # the bottle's own highlight
    return np.clip(warped * (shade * stripe)[None, :, None], 0, 255).astype(np.uint8)


def photograph(panel: Image.Image, shot: Shot) -> Image.Image:
    rng = np.random.default_rng(shot.seed)
    lab = np.asarray(panel).astype(np.float32)
    if shot.glare:
        gx, gy, rx, ry, k = shot.glare
        h, w = lab.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        g = np.exp(-(((xx - gx * w) / (rx * w)) ** 2 + ((yy - gy * h) / (ry * h)) ** 2))
        lab = lab + (255 - lab) * (k * g)[..., None]
    lab = wrap_cylinder(lab.astype(np.uint8), shot.curve)
    lh, lw = lab.shape[:2]

    # Bottle and scene around the label.
    pad_x, pad_y = int(lw * 0.18), int(lh * 0.22)
    H, W = lh + 2 * pad_y, lw + 2 * pad_x + int(lw * 0.5)
    scene = np.empty((H, W, 3), np.float32)
    scene[:] = shot.scene
    scene *= np.linspace(0.75, 1.15, W)[None, :, None]
    bx0, bx1 = int(lw * 0.25), int(lw * 0.25) + lw + 2 * pad_x - int(lw * 0.1)
    cols = np.arange(bx1 - bx0)
    phi = (cols / (bx1 - bx0) - 0.5) * np.pi * 0.9
    bottle = np.array(shot.glass, np.float32)[None, :] * (0.5 + 0.6 * np.cos(phi))[:, None]
    scene[int(pad_y * 0.3):, bx0:bx1] = bottle[None, :, :]
    lx = bx0 + (bx1 - bx0 - lw) // 2
    scene[pad_y:pad_y + lh, lx:lx + lw] = lab

    img = np.clip(scene, 0, 255).astype(np.uint8)
    if shot.tilt:
        t = shot.tilt
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        dst = np.float32([[W * t, H * t * 0.6], [W * (1 - t * 0.3), 0], [W, H], [W * t * 0.4, H * (1 - t * 0.5)]])
        img = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (W, H), borderMode=cv2.BORDER_REPLICATE)
    if shot.angle:
        m = cv2.getRotationMatrix2D((W / 2, H / 2), shot.angle, 1.0)
        img = cv2.warpAffine(img, m, (W, H), borderMode=cv2.BORDER_REPLICATE)
    scale = shot.out_long / max(W, H)
    img = cv2.resize(img, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)
    if shot.blur:
        img = cv2.GaussianBlur(img, (0, 0), shot.blur)
    img = np.clip(img + rng.normal(0, shot.noise, img.shape), 0, 255).astype(np.uint8)
    return Image.fromarray(img)


# ---------------------------------------------------------------- cases

APP = {
    "brand_name": "OLD TOM DISTILLERY", "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)", "net_contents": "750 mL",
    "producer_name_address": "Old Tom Distillery, Bardstown, Kentucky",
    "country_of_origin": None, "is_import": False, "beverage_type": "spirits",
}

BEER = dict(brand="IRON GATE BREWING", class_type="India Pale Ale", alcohol="6.8% Alc./Vol.", net="12 FL. OZ.",
            producer="Brewed and Canned by Iron Gate Brewing Co., Asheville, North Carolina")
BEER_APP = {"brand_name": "IRON GATE BREWING", "class_type": "India Pale Ale", "alcohol_content": "6.8% Alc./Vol.",
            "net_contents": "12 fl oz", "producer_name_address": "Iron Gate Brewing Co., Asheville, North Carolina",
            "country_of_origin": None, "is_import": False, "beverage_type": "beer"}
WINE = dict(brand="Bella Colina", class_type="Napa Valley Cabernet Sauvignon", alcohol="Alc. 13.5% by Vol.",
            net="750 mL", producer="Produced and Bottled by Bella Colina Cellars, Napa, California")
WINE_APP = {"brand_name": "BELLA COLINA", "class_type": "Napa Valley Cabernet Sauvignon",
            "alcohol_content": "13.5%", "net_contents": "750 mL",
            "producer_name_address": "Bella Colina Cellars, Napa, California",
            "country_of_origin": None, "is_import": False, "beverage_type": "wine"}
VODKA = dict(brand="NORTHERN LIGHT", class_type="Vodka", alcohol="40% Alc./Vol. (80 Proof)", net="1 L",
             producer="Distilled and Bottled by Northern Light Spirits, Minneapolis, Minnesota")
VODKA_APP = {"brand_name": "NORTHERN LIGHT", "class_type": "Vodka", "alcohol_content": "40% Alc./Vol. (80 Proof)",
             "net_contents": "1 L", "producer_name_address": "Northern Light Spirits, Minneapolis, Minnesota",
             "country_of_origin": None, "is_import": False, "beverage_type": "spirits"}
SCOTCH = dict(brand="GLEN ARDOCH", class_type="Single Malt Scotch Whisky", alcohol="43% Alc./Vol.", net="750 mL",
              producer="Imported by Highland Imports Ltd., New York, NY", country="Product of Scotland")
SCOTCH_APP = {"brand_name": "GLEN ARDOCH", "class_type": "Single Malt Scotch Whisky", "alcohol_content": "43%",
              "net_contents": "750 mL", "producer_name_address": "Highland Imports Ltd., New York, NY",
              "country_of_origin": "Scotland", "is_import": True, "beverage_type": "spirits"}

CLASSIC = Design()
CRAFT = Design(bg=(232, 225, 205), ink=(20, 30, 25), accent=(25, 70, 45), brand_font="UnifrakturMaguntia-Book.ttf",
               brand_size=96, text_font="LiberationSans-Regular.ttf", warn_size=17)
SCRIPT = Design(bg=(250, 248, 244), ink=(40, 30, 50), accent=(110, 20, 50), brand_font="Lobster-Regular.ttf",
                brand_size=110, text_font="LiberationSerif-Regular.ttf", warn_size=18, border=False)
DARK = Design(bg=(18, 20, 28), ink=(235, 235, 240), accent=(180, 200, 230), brand_font="BebasNeue-Regular.ttf",
              brand_size=120, text_font="LiberationSans-Regular.ttf", warn_size=18)
TINY = Design(warn_size=14)

GENTLE = Shot()
CURVED = Shot(curve=2.1, blur=0.9, seed=2)
ANGLED = Shot(curve=1.6, angle=-7, tilt=0.08, seed=3)
GLARE_SIDE = Shot(curve=1.6, glare=(0.78, 0.25, 0.16, 0.12, 0.9), seed=4)
GLARE_WARNING = Shot(curve=1.6, glare=(0.40, 0.655, 0.20, 0.035, 0.97), seed=5)
SOFT = Shot(curve=1.5, blur=1.6, noise=7, jpeg=70, seed=6)
SMALL = Shot(curve=1.5, out_long=1100, seed=7)

ALL_PASS = {**{f: "pass" for f in ("brand_name", "class_type", "alcohol_content", "net_contents",
                                   "producer_name_address")},
            "government_warning": ["pass", "needs_review"]}  # bold may not be confirmable in a photo


@dataclass
class Case:
    name: str
    description: str
    truth: str  # compliant | violation | review
    label: Label
    app: dict
    design: Design = field(default_factory=Design)
    shot: Shot = field(default_factory=Shot)
    panels: tuple = ("full",)  # ("full",) or ("front", "back") or ("front",)
    all_sides: bool = True
    hard: bool = False  # degraded enough that Needs review is an acceptable answer for the cloud engine
    fields: dict = field(default_factory=dict)  # expected per-field status (cloud), a status or a list


def L(base=None, **kw) -> Label:
    return Label(**{**(base or {}), **kw})


CASES = [
    # ---- compliant
    Case("bourbon_front_back", "Bourbon, front and back labels photographed separately; all compliant.",
         "compliant", L(), APP, CLASSIC, GENTLE, ("front", "back"), fields=ALL_PASS),
    Case("bourbon_curved", "Compliant bourbon label on a strongly curved bottle.", "compliant", L(), APP,
         CLASSIC, CURVED, hard=True),
    Case("bourbon_angled", "Compliant bourbon label photographed at an angle.", "compliant", L(), APP,
         CLASSIC, ANGLED, hard=True),
    Case("bourbon_glare_side", "Compliant label with glare away from the warning.", "compliant", L(), APP,
         CLASSIC, GLARE_SIDE, hard=True),
    Case("bourbon_glare_warning", "Compliant label with strong glare across the warning.", "compliant", L(), APP,
         CLASSIC, GLARE_WARNING, hard=True),
    Case("bourbon_soft_focus", "Compliant label, out of focus and compressed.", "compliant", L(), APP,
         CLASSIC, SOFT, hard=True),
    Case("bourbon_tiny_warning", "Compliant label with a very small, condensed warning.", "compliant", L(), APP,
         TINY, GENTLE, hard=True),
    Case("bourbon_small_photo", "Compliant label in a small photo (1100 px).", "compliant", L(), APP,
         CLASSIC, SMALL, hard=True),
    Case("beer_blackletter", "Craft beer: blackletter brand, condensed warning, can curvature.", "compliant",
         L(BEER), BEER_APP, CRAFT, Shot(curve=1.9, glass=(150, 150, 155), seed=8), hard=True),
    Case("wine_script_front_back", "Wine with a script-font brand; warning on the back label.", "compliant",
         L(WINE), WINE_APP, SCRIPT, Shot(curve=1.3, glass=(30, 60, 30), seed=9), ("front", "back")),
    Case("vodka_dark_label", "Light text on a dark label.", "compliant", L(VODKA), VODKA_APP, DARK,
         Shot(curve=1.5, glass=(200, 210, 215), seed=10), hard=True),
    Case("scotch_import", "Imported scotch with \"Product of Scotland\".", "compliant", L(SCOTCH), SCOTCH_APP,
         CLASSIC, Shot(curve=1.6, seed=11), hard=True),
    Case("brand_case_styled", "Label brand in title-case script (\"Stone's Throw\"), application in capitals.",
         "compliant", L(brand="Stone's Throw", producer="Distilled and Bottled by Stone's Throw Distillery, "
                                                         "Frankfort, Kentucky"),
         {**APP, "brand_name": "STONE'S THROW", "producer_name_address": "Stone's Throw Distillery, Frankfort, Kentucky"},
         SCRIPT, GENTLE, hard=True),

    # ---- violations
    Case("warning_title_case_curved", "Warning heading in title case (\"Government Warning:\").", "violation",
         L(heading="Government Warning:"), APP, CLASSIC, CURVED, fields={"government_warning": "fail"}),
    Case("warning_heading_regular", "Warning heading in regular weight (not bold), condensed type.", "violation",
         L(heading_bold=False), APP, CLASSIC, GENTLE, hard=True,
         fields={"government_warning": ["fail", "needs_review"]}),
    Case("warning_all_bold", "Whole warning in bold; the body must not be bold.", "violation",
         L(body_bold=True), APP, CLASSIC, GENTLE, hard=True, fields={"government_warning": ["fail", "needs_review"]}),
    Case("warning_altered_word", "Warning says \"may cause serious health problems\".", "violation",
         L(body=BODY.replace("cause health", "cause serious health")), APP, CLASSIC, GENTLE,
         fields={"government_warning": "fail"}),
    Case("warning_altered_under_glare", "Altered warning (\"may cause serious health problems\") with glare "
         "partly washing out that line: a reader that fills in the standard text would miss it.", "violation",
         L(body=BODY.replace("cause health", "cause serious health")), APP, CLASSIC,
         Shot(curve=1.6, glare=(0.40, 0.68, 0.20, 0.03, 0.85), seed=16), hard=True,
         fields={"government_warning": ["fail", "needs_review"]}),
    Case("warning_missing_clause", "Warning omits \"or operate machinery\".", "violation",
         L(body=BODY.replace(" or operate machinery", "")), APP, TINY, Shot(curve=1.6, seed=12),
         fields={"government_warning": "fail"}),
    Case("warning_paraphrased", "Warning paraphrased in plain words.", "violation",
         L(body="(1) The Surgeon General advises women not to drink alcohol while pregnant because of the "
                "risk of birth defects. (2) Drinking alcohol impairs your ability to drive or operate "
                "machinery and may cause health problems."), APP, CLASSIC, GENTLE,
         fields={"government_warning": "fail"}),
    Case("warning_no_colon_back", "Back label warning heading without the colon.", "violation",
         L(heading="GOVERNMENT WARNING"), APP, CLASSIC, GENTLE, ("front", "back"),
         fields={"government_warning": "fail"}),
    Case("warning_missing_all_sides", "No warning anywhere; front and back both supplied.", "violation",
         L(warning=False), APP, CLASSIC, GENTLE, ("front", "back"), fields={"government_warning": "fail"}),
    Case("abv_mismatch_photo", "Label 40% (80 Proof), application 45% (90 Proof).", "violation",
         L(alcohol="40% Alc./Vol. (80 Proof)"), APP, CLASSIC, ANGLED, fields={"alcohol_content": "fail"}),
    Case("proof_inconsistent_photo", "Label says 45% but 80 Proof.", "violation",
         L(alcohol="45% Alc./Vol. (80 Proof)"), APP, CLASSIC, GENTLE, fields={"alcohol_content": "fail"}),
    Case("net_contents_mismatch", "Label 700 mL, application 750 mL.", "violation",
         L(net="700 mL"), APP, CLASSIC, GLARE_SIDE, fields={"net_contents": "fail"}),
    Case("brand_different", "Label brand OLD TOM RESERVE, application OLD OAK DISTILLERY.", "violation",
         L(brand="OLD TOM RESERVE"), {**APP, "brand_name": "OLD OAK DISTILLERY"}, CLASSIC, GENTLE,
         fields={"brand_name": "fail"}),
    Case("beer_abv_mismatch", "Beer label 7.8%, application 6.8%.", "violation", L(BEER, alcohol="7.8% Alc./Vol."),
         BEER_APP, CRAFT, Shot(curve=1.9, glass=(150, 150, 155), seed=13), fields={"alcohol_content": "fail"}),
    Case("import_no_country_photo", "Imported scotch with no country of origin; all sides supplied.", "violation",
         L(SCOTCH, country=None), SCOTCH_APP, CLASSIC, Shot(curve=1.6, seed=14),
         fields={"country_of_origin": "fail"}),
    Case("vodka_warning_lowercase", "Dark label; heading \"Government warning:\".", "violation",
         L(VODKA, heading="Government warning:"), VODKA_APP, DARK, Shot(curve=1.5, glass=(200, 210, 215), seed=15),
         fields={"government_warning": "fail"}),

    # ---- the right answer is Needs review
    Case("front_only", "Only the front label supplied: no warning visible, but it may be on the back.", "review",
         L(), APP, CLASSIC, GENTLE, ("front",), all_sides=False,
         fields={"government_warning": "needs_review", "producer_name_address": "needs_review"}),
    Case("brand_one_letter_photo", "Label OLD TOMB DISTILLERY vs application OLD TOM DISTILLERY.", "review",
         L(brand="OLD TOMB DISTILLERY"), APP, CLASSIC, GENTLE, fields={"brand_name": "needs_review"}),
]


def expected(c: Case) -> dict:
    if c.truth == "compliant":
        # Bold must be confirmed from the pixels to pass; on small print in a photo it often cannot be.
        vision = ["pass", "needs_review"]
        local = ["needs_review"]  # offline OCR cannot verify bold
    elif c.truth == "violation":
        vision = ["fail", "needs_review"] if c.hard else ["fail"]
        local = ["fail", "needs_review"]
    else:
        vision, local = ["needs_review"], ["needs_review"]
    return {"azure_vision": {"overall": vision, "fields": c.fields},
            "local_ocr": {"overall": local, "fields": {}}}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    for c in CASES:
        images = []
        for i, part in enumerate(c.panels):
            shot = Shot(**{**c.shot.__dict__, "seed": c.shot.seed * 10 + i})
            img = photograph(render_panel(c.label, c.design, part), shot)
            name = f"{c.name}.jpg" if len(c.panels) == 1 and part == "full" else f"{c.name}_{part}.jpg"
            img.save(OUT / name, "JPEG", quality=c.shot.jpeg)
            images.append(name)
        meta = {"case": c.name, "description": c.description, "truth": c.truth, "simulated_photo": True,
                "images": images, "image": images[0], "all_sides": c.all_sides,
                "label": c.label.__dict__, "application": c.app, "expected": expected(c)}
        (OUT / f"{c.name}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {len(CASES)} photo fixtures to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
