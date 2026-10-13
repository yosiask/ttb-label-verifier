"""Image preparation for OCR: EXIF rotate, resize, grayscale, CLAHE contrast, small-angle deskew."""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 60_000_000  # refuse decompression bombs

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class InvalidImageError(ValueError):
    """The bytes are not a supported, decodable image."""


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise InvalidImageError("The file is not a readable JPEG, PNG or WebP image.") from e
    if fmt not in ALLOWED_FORMATS:
        raise InvalidImageError(f"{fmt or 'This'} images are not supported. Use JPEG, PNG or WebP.")
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        img = bg
    return img


def resize_for_ocr(gray: np.ndarray, target_long: int = 2000, min_long: int = 1400) -> np.ndarray:
    h, w = gray.shape[:2]
    long_edge = max(h, w)
    if long_edge > target_long:
        s = target_long / long_edge
        return cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    if long_edge < min_long:
        s = min_long / long_edge
        return cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
    return gray


def estimate_skew(gray: np.ndarray, max_angle: float = 15.0) -> float:
    """Angle (degrees) that makes text lines horizontal, by maximizing row-profile sharpness."""
    small = gray
    h, w = gray.shape
    if max(h, w) > 900:
        s = 900 / max(h, w)
        small = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    sh, sw = binary.shape
    center = (sw / 2, sh / 2)

    def sharpness(angle: float) -> float:
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rot = cv2.warpAffine(binary, m, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)
        rows = rot.sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(rows) ** 2))

    coarse = np.arange(-max_angle, max_angle + 0.01, 1.0)
    best = max(coarse, key=sharpness)
    fine = np.arange(best - 1.0, best + 1.01, 0.25)
    return float(max(fine, key=sharpness))


def rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(gray, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=255)


def prepare_for_ocr(img: Image.Image) -> tuple[np.ndarray, list[str]]:
    """Return a grayscale array ready for Tesseract, plus notes on what was done."""
    gray, _, notes = prepare_for_ocr_with_plain(img)
    return gray, notes


def prepare_for_ocr_with_plain(img: Image.Image) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """As prepare_for_ocr, plus the same pixels without contrast enhancement or inversion, in the
    same geometry: close-up re-reads of decorative type read some letters better from it."""
    notes: list[str] = []
    gray = np.array(img.convert("L"))
    gray = resize_for_ocr(gray)
    plain = gray.copy()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    # Labels with light text on a dark background read better inverted.
    if float(np.median(gray)) < 110:
        gray = 255 - gray
        notes.append("inverted light-on-dark image")
    angle = estimate_skew(gray)
    if abs(angle) >= 0.5:
        gray = rotate(gray, angle)
        plain = rotate(plain, angle)
        notes.append(f"straightened by {angle:+.1f} degrees")
    return gray, plain, notes
