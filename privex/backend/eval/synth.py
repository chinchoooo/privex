"""
Synthetic PII corpus with gold spans, including hard negatives
(tracking numbers, order IDs, helplines, invoice dates) that a naive
detector would over-redact.

    python -m eval.synth --n 500 --seed 7 --out eval/data/synth.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

from privex_core.text.validators import verhoeff_check_digit

FIRST = ["Aarav", "Priya", "Rahul", "Ananya", "Vikram", "Sneha", "Arjun", "Kavya", "John", "Emily",
         "Michael", "Sarah", "David", "Maria", "Wei", "Fatima", "Carlos", "Olivia", "Ravi", "Meera"]
LAST = ["Sharma", "Iyer", "Verma", "Reddy", "Nair", "Gupta", "Smith", "Johnson", "Williams", "Brown",
        "Garcia", "Chen", "Khan", "Patel", "Rodriguez", "Kumar", "Das", "Menon", "Singh", "Lee"]
STREETS = ["MG Road", "Park Street", "Main Street", "Oak Avenue", "Gandhi Nagar", "Lake View Road",
           "Elm Street", "Station Road", "Church Lane", "Sunset Boulevard"]
CITIES = [("Bengaluru", "560001"), ("Mumbai", "400050"), ("Chennai", "600020"), ("Pune", "411001")]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
UPI = ["okaxis", "ybl", "oksbi", "paytm", "okhdfcbank", "ibl"]


def _digits(r, n, first="123456789"):
    return r.choice(first) + "".join(r.choice(string.digits) for _ in range(n - 1))


def _luhn_complete(prefix: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(prefix)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return prefix + str((10 - total % 10) % 10)


def gen_values(r: random.Random) -> dict[str, tuple[str, str | None]]:
    """slot → (surface text, gold type or None for hard negatives)."""
    first, last = r.choice(FIRST), r.choice(LAST)
    card = _luhn_complete(r.choice(["4", "51", "52", "6"]) + "".join(r.choice(string.digits) for _ in range(14 if True else 0)))[:16]
    card = _luhn_complete(card[:15])
    aad = _digits(r, 11, "23456789")
    aad += verhoeff_check_digit(aad)
    city, pin = r.choice(CITIES)
    y, m, d = r.randint(1950, 2004), r.randint(1, 12), r.randint(1, 28)
    tracking = "".join(r.choice(string.digits) for _ in range(16))
    while _luhn_complete(tracking[:15]) == tracking:      # make sure it is NOT a valid card
        tracking = "".join(r.choice(string.digits) for _ in range(16))
    return {
        "name": (f"{first} {last}", "PERSON"),
        "first": (first, "PERSON"),
        "phone": (r.choice([f"+91 {_digits(r, 5, '6789')} {_digits(r, 5, '0123456789')}",
                            f"{_digits(r, 10, '6789')}",
                            f"({_digits(r, 3, '23456789')}) {_digits(r, 3)}-{_digits(r, 4)}"]), "PHONE"),
        "email": (f"{first.lower()}.{last.lower()}{r.randint(1, 99)}@{r.choice(['gmail.com', 'outlook.com', 'yahoo.in'])}", "EMAIL"),
        "card": (" ".join(card[i:i + 4] for i in range(0, 16, 4)) if r.random() < 0.5 else card, "CREDIT_CARD"),
        "cvv": (_digits(r, 3), "CVV"),
        "aadhaar": (f"{aad[:4]} {aad[4:8]} {aad[8:]}", "AADHAAR"),
        "pan": ("".join(r.choice(string.ascii_uppercase) for _ in range(3)) + r.choice("PCHFAT")
                + last[0].upper() + _digits(r, 4, string.digits) + r.choice(string.ascii_uppercase), "PAN"),
        "ifsc": (r.choice(["HDFC", "ICIC", "SBIN", "UTIB"]) + "0" + _digits(r, 6, string.digits), "IFSC"),
        "account": (_digits(r, r.randint(11, 16)), "BANK_ACCOUNT"),
        "upi": (f"{first.lower()}{r.randint(1, 999)}@{r.choice(UPI)}", "UPI"),
        "dob": (r.choice([f"{d:02d}/{m:02d}/{y}", f"{MONTHS[m - 1]} {d}, {y}", f"{d} {MONTHS[m - 1]} {y}"]), "DATE_OF_BIRTH"),
        "address": (f"{r.randint(1, 999)} {r.choice(STREETS)}, {city} {pin}", "ADDRESS"),
        "otp": (_digits(r, 6, string.digits), "OTP"),
        "ssn": (f"{r.randint(100, 665)}-{r.randint(10, 99)}-{r.randint(1000, 9999)}", "SSN"),
        # hard negatives
        "tracking": (tracking, None),
        "order": (f"OD{_digits(r, 12)}", None),
        "invoice_date": (f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/2024", None),
        "helpline": (f"1800-{_digits(r, 3)}-{_digits(r, 4)}", None),
        "amount": (f"{r.randint(100, 99999)}.{r.randint(10, 99)}", None),
        "sku": (f"SKU-{_digits(r, 6)}", None),
    }


TEMPLATES = [
    "Hi, I'm {name}. You can reach me at {phone} or {email}.",
    "Customer: {name}\nPhone: {phone}\nEmail: {email}\nAddress: {address}",
    "Please charge my card {card}, CVV {cvv}. The order {order} totals Rs {amount}.",
    "Your OTP is {otp}. Do not share it with anyone. For help call our customer care {helpline}.",
    "Aadhaar: {aadhaar}\nPAN: {pan}\nDate of Birth: {dob}",
    "Transfer to account number {account}, IFSC {ifsc}. Beneficiary name: {name}.",
    "Pay to {upi} for invoice dated {invoice_date}.",
    "Your package with tracking number {tracking} will arrive soon. Item {sku}.",
    "Dear {first}, your appointment is confirmed. We have your DOB as {dob}.",
    "Employee {name} (born {dob}) lives at {address}.",
    "SSN: {ssn}. Contact {name} on {phone}.",
    "Invoice date {invoice_date}. Total {amount}. Support: {helpline}. Ref {order}.",
    "My card number is {card} and expiry 08/2027. Name on card: {name}.",
    "Send the documents to {email}. My PAN is {pan} and Aadhaar number {aadhaar}.",
]


def render(template: str, values: dict) -> dict:
    text, spans, pos, i = [], [], 0, 0
    import re
    for m in re.finditer(r"\{(\w+)\}", template):
        lit = template[i:m.start()]
        text.append(lit); pos += len(lit)
        surface, gold = values[m.group(1)]
        if gold:
            spans.append({"start": pos, "end": pos + len(surface), "type": gold})
        text.append(surface); pos += len(surface)
        i = m.end()
    text.append(template[i:])
    return {"text": "".join(text), "entities": spans}


def generate(n: int, seed: int) -> list[dict]:
    r = random.Random(seed)
    return [render(r.choice(TEMPLATES), gen_values(r)) for _ in range(n)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="eval/data/synth.jsonl")
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for row in generate(a.n, a.seed):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {a.n} examples → {a.out}")
