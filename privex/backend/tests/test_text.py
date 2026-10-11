import pytest

from privex_core.text import validators as V
from privex_core.text.analyzer import Analyzer


@pytest.fixture(scope="module")
def analyzer():
    return Analyzer(threshold=0.5)


def sensitive(analyzer, text):
    return {(e.type, e.text) for e in analyzer.analyze(text) if e.score >= analyzer.threshold}


def test_validators():
    assert V.luhn("4111 1111 1111 1111")
    assert not V.luhn("4111 1111 1111 1112")
    assert V.aadhaar("2341 2341 2346")
    assert not V.aadhaar("2341 2341 2345")
    assert V.iban("GB82 WEST 1234 5698 7654 32")
    assert not V.iban("GB82 WEST 1234 5698 7654 33")
    assert V.us_ssn("123-45-6789") and not V.us_ssn("000-45-6789")
    assert V.upi("rahul@okaxis") and not V.upi("rahul@example")
    assert V.ipv4("192.168.1.10") and not V.ipv4("999.1.1.1")


@pytest.mark.parametrize("text,expected", [
    ("Email me at a.b@example.com", ("EMAIL", "a.b@example.com")),
    ("Card: 4111 1111 1111 1111", ("CREDIT_CARD", "4111 1111 1111 1111")),
    ("Aadhaar 2341 2341 2346", ("AADHAAR", "2341 2341 2346")),
    ("PAN ABCPE1234F", ("PAN", "ABCPE1234F")),
    ("Call +91 98765 43210", ("PHONE", "+91 98765 43210")),
    ("DOB: 07/01/1973", ("DATE_OF_BIRTH", "07/01/1973")),
    ("Your OTP is 482913", ("OTP", "482913")),
    ("Account No: 50100234567890", ("BANK_ACCOUNT", "50100234567890")),
    ("Pay to rahul@okaxis", ("UPI", "rahul@okaxis")),
    ("Customer: Priya Sharma", ("PERSON", "Priya Sharma")),
    ("Address: 2570 24th Street, Anytown CA 95818", ("ADDRESS", "2570 24th Street, Anytown CA 95818")),
])
def test_detects(analyzer, text, expected):
    assert expected in sensitive(analyzer, text)


@pytest.mark.parametrize("text", [
    "Your package with tracking number 7289905958278527 will arrive soon.",
    "Invoice date 03/04/2024. Total 4599.00",
    "For help call our customer care 1800-123-4567.",
    "contact us at the front desk",
    "COMMERCIAL DRIVER'S LICENSE",          # 'DR' must not be read as the title Dr.
])
def test_hard_negatives(analyzer, text):
    assert sensitive(analyzer, text) == set()


@pytest.mark.parametrize("text,expected", [
    # found by error analysis on the Nemotron-PII dev split
    ("- **First Name:** Lois\n- **Last Name:** Elrod", ("PERSON", "Lois")),
    ("| Last Name            | Sharp                   |", ("PERSON", "Sharp")),
    ("Contact Kavya Smith on 555-0101", ("PERSON", "Kavya Smith")),
    ("Fax Number: 2-283-4590", ("PHONE", "2-283-4590")),
    ("The phone number for contact is 2935 3296.", ("PHONE", "2935 3296")),
    ("credit debit card 5432 1796 5938 7402", ("CREDIT_CARD", "5432 1796 5938 7402")),
    ("the biometric identifier M73489561239 was used", ("GOV_ID", "M73489561239")),
    ("I reside at Baghramyan Avenue 53, Artashat.", ("ADDRESS", "Baghramyan Avenue 53, Artashat")),
    ("located at 112 Nisqually Rd, Pomona, 91766.", ("ADDRESS", "112 Nisqually Rd, Pomona, 91766")),
    ("user name fjensen, with", ("CREDENTIAL", "fjensen")),
    ("and password K9$tP@5qZmR. Once", ("CREDENTIAL", "K9$tP@5qZmR")),
    ("cookie user_session=jf4k7m9p2r; Path=/; HttpOnly", ("CREDENTIAL", "user_session=jf4k7m9p2r; Path=/; HttpOnly")),
    ("MAC address 00:1A:2B:3C:4D:5E", ("DEVICE_ID", "00:1A:2B:3C:4D:5E")),
    ("swift bic HGTIUS7K901 for", ("SWIFT_BIC", "HGTIUS7K901")),
    ("**License Plate:** SMA 1234D", ("VEHICLE_ID", "SMA 1234D")),
])
def test_detects_forms_and_secrets(analyzer, text, expected):
    assert expected in sensitive(analyzer, text)


@pytest.mark.parametrize("text", [
    "**Customer Information**\n\nWe address issues promptly and effectively.",
    "2. Maintenance Schedule\n    2.1 Routine Tasks",
    "Your password must be strong. Please reset your password regularly.",
    "the user name is required",
    "Meeting at 10:35:58 sharp",
])
def test_heading_and_prose_negatives(analyzer, text):
    assert sensitive(analyzer, text) == set()


def test_closest_context_wins(analyzer):
    found = sensitive(analyzer, "DOB: 07/01/1973  ISS 03/04/2020")
    assert ("DATE_OF_BIRTH", "07/01/1973") in found
    assert not any(v == "03/04/2020" for _, v in found)


def test_propagation(analyzer):
    text = "Name: Ravi Menon. Later, Ravi Menon signed the form."
    assert sum(1 for t, v in [(e.type, e.text) for e in analyzer.analyze(text)] if v == "Ravi Menon") == 2


def test_redact_styles(analyzer):
    assert analyzer.redact("PAN ABCPE1234F", style="tag") == "PAN [PAN]"
    assert analyzer.redact("PAN ABCPE1234F") == "PAN " + "█" * 10


def test_id_card_caps_name(analyzer):
    doc = "DRIVER LICENSE\nDL: D1234567\nMOTORIST HD MORGAN\nDOB: 07/01/1973"
    found = sensitive(analyzer, doc)
    assert ("PERSON", "MOTORIST HD MORGAN") in found
    assert ("DRIVER_LICENSE", "D1234567") in found


def test_synthetic_eval_floor():
    """Guardrail: the synthetic benchmark must not regress (it is also the dev set)."""
    from eval.run_eval import evaluate
    from eval.synth import generate
    res = evaluate(generate(200, 99), Analyzer())
    assert res["f1"] > 0.97
    assert res["leak_rate"] < 0.02
