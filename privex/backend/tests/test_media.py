import numpy as np
import pytest

from privex_core.audio import Word, find_sensitive
from privex_core.vision import image as img_mod
from privex_core.vision import ocr
from privex_core.video import _motion_cover


def words(s):
    return [Word(t, i, i + 0.5) for i, t in enumerate(s.split())]


@pytest.mark.parametrize("speech,etype,value", [
    ("call me on nine eight seven six five four three two one zero", "PHONE", "9876543210"),
    ("My date of birth is January 7, 1973.", "DATE_OF_BIRTH", "January 7, 1973"),
    ("my otp is double five one two", "OTP", "5512"),
    ("card number 4111 1111 1111 1111 thanks", "CREDIT_CARD", "4111111111111111"),
])
def test_audio_spoken_numbers(speech, etype, value):
    _, ents, ranges = find_sensitive(words(speech))
    assert any(e["type"] == etype and e["text"] == value and e["sensitive"] for e in ents)
    assert ranges


def test_span_to_boxes_partial_line():
    line = ocr.OcrLine("Phone 9876543210", np.array([[0, 0], [160, 0], [160, 20], [0, 20]], np.float32), 0.9)
    ocr.build_document([line])
    (box,) = ocr.span_to_boxes([line], 6, 16, pad=0)
    assert 50 <= box["x"] <= 60 and box["x"] + box["w"] >= 159   # covers only the number


def test_apply_styles():
    img = np.full((50, 50, 3), 255, np.uint8)
    for style in ("black", "blur", "pixelate"):
        out, n = img_mod.apply(img, [{"x": 10, "y": 10, "w": 20, "h": 20}], style)
        assert n == 1 and out.shape == img.shape
    out, _ = img_mod.apply(img, [{"x": 10, "y": 10, "w": 20, "h": 20}], "black")
    assert out[20, 20].sum() == 0 and out[0, 0].sum() == 765


def test_motion_cover_spans_path():
    a = [{"x": 0, "y": 0, "w": 50, "h": 10}]
    b = [{"x": 40, "y": 5, "w": 50, "h": 10}]
    (u,) = _motion_cover(a, b, max_shift=200)
    assert u == {"x": 0, "y": 0, "w": 90, "h": 15}
