"""Checksum / structural validators used to confirm pattern matches."""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\D")


def digits(s: str) -> str:
    return _DIGITS.sub("", s)


def luhn(s: str) -> bool:
    d = digits(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def credit_card(s: str) -> bool:
    d = digits(s)
    if not luhn(d) or len(set(d)) == 1:
        return False
    # Known IIN ranges: Visa, Mastercard, Amex, Discover, RuPay, JCB, Diners, Maestro, UnionPay
    return bool(re.match(r"^(4|5[1-5]|2[2-7]|3[47]|6|35|30|36|38|50|5[6-9]|62|81|82|508|60|65)", d))


# Verhoeff tables (Aadhaar check digit)
_V_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_V_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff(s: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits(s))):
        c = _V_D[c][_V_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(s: str) -> str:
    """Return the Verhoeff check digit for a digit string (used by synthetic data)."""
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(digits(s))):
        c = _V_D[c][_V_P[(i + 1) % 8][int(ch)]]
    return str(inv[c])


def aadhaar(s: str) -> bool:
    d = digits(s)
    return len(d) == 12 and d[0] not in "01" and verhoeff(d)


def iban(s: str) -> bool:
    raw = re.sub(r"\s", "", s).upper()
    if not 15 <= len(raw) <= 34:
        return False
    rearranged = raw[4:] + raw[:4]
    num = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(num) % 97 == 1


def us_ssn(s: str) -> bool:
    d = digits(s)
    if len(d) != 9:
        return False
    area, group, serial = d[:3], d[3:5], d[5:]
    return area not in ("000", "666") and not area.startswith("9") and group != "00" and serial != "0000"


def phone(s: str) -> bool:
    d = digits(s)
    return 10 <= len(d) <= 13 and len(set(d[-10:])) > 2


def ipv4(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 and (p == "0" or not p.startswith("0")) for p in parts)


# Common UPI handles (bank PSP suffixes)
UPI_HANDLES = {
    "ybl", "ibl", "axl", "okaxis", "oksbi", "okhdfcbank", "okicici", "paytm", "upi", "apl",
    "axisbank", "icici", "hdfcbank", "sbi", "kotak", "yesbank", "idfcbank", "pnb", "boi",
    "barodampay", "fbl", "rbl", "indus", "federal", "jupiteraxis", "freecharge", "airtel",
    "jio", "slice", "naviaxis", "waicici", "wahdfcbank", "waaxis", "wasbi", "postbank", "dbs",
}


def upi(s: str) -> bool:
    return s.rsplit("@", 1)[-1].lower() in UPI_HANDLES


def ipv6(s: str) -> bool:
    import ipaddress
    if s.count(":") < 3 or (not re.search(r"[A-Fa-f]", s) and s.count(":") < 5):
        return False          # avoid clock times / ratios like 10:35:58
    try:
        return isinstance(ipaddress.ip_address(s), ipaddress.IPv6Address)
    except ValueError:
        return False
