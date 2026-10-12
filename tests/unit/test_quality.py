import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.core.quality import assess_quality, too_small_to_read


def text_image(w=1100, h=1500, fill=(250, 246, 236)):
    img = Image.new("RGB", (w, h), fill)
    d = ImageDraw.Draw(img)
    for y in range(50, h - 50, 40):
        d.text((60, y), "GOVERNMENT WARNING: (1) According to the Surgeon General " * 2, fill=(20, 20, 20))
    return img


def test_clear_image_has_no_issues():
    q = assess_quality(text_image())
    assert q.issues == [] and q.sharpness > 0.15


def test_blurry():
    q = assess_quality(text_image().filter(ImageFilter.GaussianBlur(4)))
    assert "The photo looks blurry." in q.issues


def test_dim_but_sharp_is_not_called_blurry():
    a = (np.asarray(text_image()).astype(float) * 0.35).astype(np.uint8)
    assert "The photo looks blurry." not in assess_quality(Image.fromarray(a)).issues


def test_dark():
    a = (np.asarray(text_image()).astype(float) * 0.2).astype(np.uint8)
    assert "The photo is dark." in assess_quality(Image.fromarray(a)).issues


def test_low_contrast():
    q = assess_quality(Image.new("RGB", (1000, 1000), (128, 128, 128)))
    assert "The photo has low contrast." in q.issues


def test_small_image():
    q = assess_quality(text_image(400, 500))
    assert any("small" in i for i in q.issues)
    assert not too_small_to_read(q)
    assert too_small_to_read(assess_quality(text_image(200, 250)))
