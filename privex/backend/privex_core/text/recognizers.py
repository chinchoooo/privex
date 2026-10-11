"""
Deterministic PII recognizers: regex + checksum validation + context scoring.

Each recognizer emits candidate entities with a score in [0, 1]. Scores start
at `base`, are confirmed (`valid_score`) or rejected by an optional validator,
and are moved up/down by context words found near the match. This replaces the
old LLM "contextual reasoning" with rules whose decisions are explainable and
measurable (see eval/).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from privex_core.entities import Entity
from privex_core.text import validators as V

B = r"(?<![\w])"          # left boundary: not preceded by a word char
E = r"(?![\w])"           # right boundary


def _term_regex(terms: Iterable[str]) -> re.Pattern | None:
    terms = sorted({t.lower() for t in terms}, key=len, reverse=True)
    if not terms:
        return None
    alt = "|".join(re.escape(t).replace(r"\ ", r"[\s._-]*") for t in terms)
    return re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])", re.I)


@dataclass
class PatternRecognizer:
    name: str
    type: str
    patterns: list[str]
    base: float
    context: list[str] = field(default_factory=list)
    negative_context: list[str] = field(default_factory=list)
    validator: Callable[[str], bool] | None = None
    valid_score: float = 0.9
    invalid_score: float | None = None      # None → drop when validator fails
    require_context: bool = False
    context_boost: float = 0.35
    negative_penalty: float = 0.4
    context_type: str | None = None          # re-type the entity when context matches
    window_before: int = 40
    window_after: int = 20
    flags: int = 0
    postprocess: Callable[[str, int, int], tuple[int, int] | None] | None = None

    def __post_init__(self):
        self._res = [re.compile(p, self.flags) for p in self.patterns]
        self._ctx = _term_regex(self.context)
        self._neg = _term_regex(self.negative_context)

    def analyze(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        seen: set[tuple[int, int]] = set()
        for rx in self._res:
            for m in rx.finditer(text):
                if "v" in rx.groupindex and m.group("v") is not None:
                    start, end = m.span("v")
                else:
                    start, end = m.span()
                if self.postprocess:
                    span = self.postprocess(text, start, end)
                    if span is None:
                        continue
                    start, end = span
                if end <= start or (start, end) in seen:
                    continue
                seen.add((start, end))
                ent = self._score(text, start, end)
                if ent:
                    out.append(ent)
        return out

    def _score(self, text: str, start: int, end: int) -> Entity | None:
        value = text[start:end]
        score, reasons, etype = self.base, [f"matches {self.name} pattern"], self.type

        if self.validator is not None:
            if self.validator(value):
                score = max(score, self.valid_score)
                reasons.append(f"{self.name} checksum/format valid")
            elif self.invalid_score is None:
                return None
            else:
                score = self.invalid_score
                reasons.append(f"{self.name} checksum failed")

        before = text[max(0, start - self.window_before):start]
        after = text[end:end + self.window_after]
        window = before + " " + after

        pos = _nearest(self._ctx, before, after)
        neg = _nearest(self._neg, before[-30:], after)
        # The closest context word wins: "DOB 01/02/1990  ISS 03/04/2020" → ISS governs the 2nd date.
        # On a tie the longer (more specific) phrase wins: "tracking number" beats "number".
        if pos and neg:
            if (neg[0], -len(neg[1])) < (pos[0], -len(pos[1])):
                pos = None
            else:
                neg = None

        if self.require_context and not pos:
            return None
        if pos:
            score += self.context_boost
            reasons.append(f"context '{pos[1].strip()}' nearby")
            if self.context_type:
                etype = self.context_type
        if neg:
            score -= self.negative_penalty
            reasons.append(f"negative context '{neg[1].strip()}' nearby")

        return Entity(etype, value, start, end, max(0.0, min(1.0, score)), f"regex:{self.name}", reasons)


def _nearest(rx: re.Pattern | None, before: str, after: str) -> tuple[int, str] | None:
    """Closest match of `rx` on either side of an entity → (distance in chars, matched text)."""
    if rx is None:
        return None
    best = None
    for m in rx.finditer(before):
        best = (len(before) - m.end(), m.group(0))          # last match is the closest
    m = rx.search(after)
    if m and (best is None or m.start() < best[0]):
        best = (m.start(), m.group(0))
    return best


# ── Post-processing helpers ────────────────────────────────────────────────────

# Label words that commonly follow a name on forms/ID cards; a captured name stops before these.
_FIELD_WORDS = {
    "dob", "d.o.b", "date", "birth", "address", "addr", "phone", "mobile", "tel", "email",
    "sex", "gender", "age", "id", "no", "no.", "number", "dl", "dln", "class", "exp", "iss",
    "issued", "expiry", "valid", "father", "mother", "s/o", "d/o", "w/o", "signature",
    "nationality", "blood", "height", "weight", "eyes", "hair", "account", "a/c", "pan", "aadhaar",
    "and", "is", "was", "at", "on", "from", "to", "with", "for", "the", "my", "his", "her",
    # section headings that follow generic labels ("Customer Information", "Client Agreement")
    "information", "info", "details", "agreement", "terms", "form", "data", "profile", "record",
    "records", "summary", "section", "service", "services", "support", "portal", "party", "consent",
    "policy", "plan", "report", "statement", "n/a", "na", "none", "not", "applicable", "relationship",
    "type", "status", "category", "contact", "name", "names",
}


def _trim_name(text: str, start: int, end: int) -> tuple[int, int] | None:
    tokens = list(re.finditer(r"\S+", text[start:end]))
    keep_end = start
    for t in tokens:
        if t.group(0).lower().strip(":,") in _FIELD_WORDS:
            break
        keep_end = start + t.end()
    keep_end = start + len(text[start:keep_end].rstrip(" ,.:;-"))
    if keep_end - start < 2:
        return None
    return start, keep_end


def _trim_line(text: str, start: int, end: int) -> tuple[int, int] | None:
    value = text[start:end]
    lead = len(value) - len(value.lstrip(" *|"))
    value = value[lead:]
    for stop in (" | ", "|", "**", ". "):
        if stop in value:
            value = value[:value.index(stop)]
    value = value.rstrip(" ,.;*")
    # an address has a number or at least two comma-separated parts
    if len(value) < 6 or not (re.search(r"\d", value) or "," in value):
        return None
    return start + lead, start + lead + len(value)


def _id_value(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Labelled identifier values must look like codes: >=2 digits, not a date or an amount."""
    v = text[start:end].rstrip(".,;")
    if sum(c.isdigit() for c in v) < 2:
        return None
    if re.fullmatch(r"[\d,]+\.\d{2}|\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}", v):
        return None
    return start, start + len(v)


_NOT_SECRET = {"n/a", "none", "null", "required", "provided", "redacted", "the", "is", "for", "and",
               "must", "should", "will", "to", "of", "with", "that", "this", "your", "their", "be",
               "are", "policy", "policies", "manager", "reset", "change", "protection", "field", "used"}


def _credential(text: str, start: int, end: int) -> tuple[int, int] | None:
    v = text[start:end].rstrip(".,;:)!?")
    if len(v) < 3 or v.lower() in _NOT_SECRET:
        return None
    # ordinary lowercase words after "password"/"user name" are prose, not values
    if v.isalpha() and v.islower():
        label = text[max(0, start - 30):start].lower()
        if any(k in label for k in ("user", "login", "handle")):
            from privex_core.text.ner import _lex
            if v in _lex()[1]:          # "user name is required" — a common word, not a handle
                return None
        elif len(v) < 12:
            return None
    return start, start + len(v)


# ── Recognizer catalogue ───────────────────────────────────────────────────────

NAME_VALUE = r"(?P<v>[A-Z](?:[A-Za-z'\-]*[A-Za-z]|\.)?(?:[ \t]+[A-Z](?:[A-Za-z'\-]*[A-Za-z]|\.)?){0,4})"

_ID_NEG = ["tracking number", "tracking no", "tracking id", "order number", "order no", "order id",
           "invoice number", "invoice no", "reference number", "ref no", "awb no", "consignment",
           "order", "order no", "tracking", "awb", "shipment", "invoice", "ref", "reference",
           "barcode", "sku", "isbn", "serial", "model", "batch", "lot", "receipt", "txn ref"]

_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
           r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")

RECOGNIZERS: list[PatternRecognizer] = [
    PatternRecognizer(
        "email", "EMAIL",
        [B + r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}" + E],
        base=0.95,
    ),
    PatternRecognizer(
        "upi", "UPI",
        [r"(?<![\w.@-])[A-Za-z0-9.\-_]{2,64}@[A-Za-z]{2,32}(?![\w@-])(?!\.[A-Za-z])"],
        base=0.55, validator=V.upi, valid_score=0.9, invalid_score=0.45,
        context=["upi", "vpa", "upi id", "pay to", "gpay", "phonepe", "paytm"],
    ),
    PatternRecognizer(
        "credit_card", "CREDIT_CARD",
        [B + r"\d(?:[ \-]?\d){12,18}" + E],
        base=0.5, validator=V.credit_card, valid_score=0.9, invalid_score=0.3,   # 0.65 with "card" nearby
        context=["card", "credit", "debit", "visa", "mastercard", "amex", "rupay", "card no", "cc",
                 "card number", "card ending"],
        negative_context=_ID_NEG,
    ),
    PatternRecognizer(
        "cvv", "CVV",
        [B + r"\d{3,4}" + E],
        base=0.5, require_context=True, context_boost=0.4, window_before=20, window_after=0,
        context=["cvv", "cvv2", "cvc", "cvc2", "security code", "card verification"],
    ),
    PatternRecognizer(
        "otp", "OTP",
        [B + r"\d{4,8}" + E],
        base=0.5, require_context=True, context_boost=0.35, window_before=40, window_after=30,
        context=["otp", "one time password", "one-time password", "verification code",
                 "passcode", "pin", "mpin", "security pin", "auth code"],
    ),
    PatternRecognizer(
        "iban", "IBAN",
        [B + r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}" + E],
        base=0.3, validator=V.iban, valid_score=0.95,
    ),
    PatternRecognizer(
        "ifsc", "IFSC",
        [B + r"[A-Z]{4}0[A-Z0-9]{6}" + E],
        base=0.7, context=["ifsc", "branch", "bank"], context_boost=0.2,
    ),
    PatternRecognizer(
        "aadhaar", "AADHAAR",
        [B + r"[2-9]\d{3}[ \-]?\d{4}[ \-]?\d{4}" + E],
        base=0.5, validator=V.aadhaar, valid_score=0.9, invalid_score=0.3,
        context=["aadhaar", "aadhar", "uidai", "uid", "enrolment", "government of india"],
        context_boost=0.45, negative_context=_ID_NEG,
    ),
    PatternRecognizer(
        "pan", "PAN",
        [B + r"[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]" + E],
        base=0.85, context=["pan", "permanent account", "income tax"], context_boost=0.1,
    ),
    PatternRecognizer(
        "ssn", "SSN",
        [B + r"\d{3}-\d{2}-\d{4}" + E, B + r"\d{9}" + E],
        base=0.45, validator=V.us_ssn, valid_score=0.6, invalid_score=None,
        context=["ssn", "social security", "ss#", "ss no"], context_boost=0.35,
        negative_context=_ID_NEG,
    ),
    PatternRecognizer(
        "phone", "PHONE",
        [
            r"(?<![\w+])(?:\+91[\-\s]?|0)?[6-9]\d{4}[\-\s]?\d{5}" + E,                       # India
            r"(?<![\w+])(?:\+?1[\-.\s]?)?\(?[2-9]\d{2}\)?[\-.\s]?\d{3}[\-.\s]\d{4}" + E,      # NANP
            r"(?<![\w+])\+\d{1,3}[\-\s]?\(?\d{1,4}\)?(?:[\-\s]?\d){6,11}" + E,              # international
        ],
        base=0.6, validator=V.phone, valid_score=0.6,
        context=["phone", "mobile", "mob", "cell", "tel", "telephone", "call", "contact", "whatsapp", "ph", "fax"],
        context_boost=0.3,
        negative_context=["toll free", "toll-free", "customer care", "helpline", "support"] + _ID_NEG,
        negative_penalty=0.35,
    ),
    PatternRecognizer(
        "phone_context", "PHONE",          # any national format, but only right after a phone/fax cue
        [r"(?<![\w+])\+?\(?\d[\d \-.()]{4,18}\d" + E],
        base=0.45, require_context=True, context_boost=0.35, window_before=35, window_after=0,
        validator=lambda v: 7 <= len(V.digits(v)) <= 15, valid_score=0.45,
        context=["phone", "phone number", "telephone", "tel", "mobile", "cell", "fax", "fax number",
                 "call", "contact number", "whatsapp", "reach me at", "reach us at", "ph"],
        negative_context=["toll free", "toll-free", "helpline", "customer care", "customer service", "support"],
    ),
    PatternRecognizer(
        "ipv4", "IP_ADDRESS",
        [B + r"\d{1,3}(?:\.\d{1,3}){3}" + E],
        base=0.5, validator=V.ipv4, valid_score=0.6, context=["ip", "ip address", "host"],
    ),
    PatternRecognizer(
        "bank_account", "BANK_ACCOUNT",
        [B + r"\d{9,18}" + E, B + r"\d{2,6}(?:[ \-]\d{2,8}){1,4}" + E],
        base=0.5, require_context=True, context_boost=0.4, window_before=50, window_after=0,
        context=["account", "account no", "account number", "a/c", "ac no", "acct", "acc no",
                 "savings", "current account", "beneficiary", "bank account"],
        negative_context=_ID_NEG,
    ),
    PatternRecognizer(
        "passport", "PASSPORT",
        [B + r"[A-PR-WY][1-9]\d ?\d{4}[1-9]" + E, B + r"[A-Z]{1,2}\d{6,8}" + E],
        base=0.3, context=["passport", "passport no", "travel document"], context_boost=0.55,
    ),
    PatternRecognizer(
        "driver_license", "DRIVER_LICENSE",
        [
            B + r"[A-Z]{2}[\-\s]?\d{2}[\-\s]?(?:19|20)\d{2}\d{7}" + E,     # India: MH14 20110012345
            B + r"\d?[A-Z]{1,2}\d{5,14}" + E,                               # US-style: D1234567, 1D123456789
        ],
        base=0.3, context=["dl", "dln", "driver", "driving", "license", "licence", "lic no", "lic"],
        context_boost=0.55,
    ),
    PatternRecognizer(
        "dl_number", "DRIVER_LICENSE",
        [B + r"\d{5,12}(?:[ \-]\d{2,6}){0,2}" + E],
        base=0.5, require_context=True, context_boost=0.35, window_before=12, window_after=0,
        context=["dl", "dln", "dl no", "lic no", "license no", "licence no", "license number"],
    ),
    PatternRecognizer(
        "gov_id", "GOV_ID",
        [B + r"[A-Z]{1,5}[\-/]?\d{3,12}" + E, B + r"\d{4,12}" + E, B + r"[A-Z]{3}\d{7}" + E],
        base=0.45, require_context=True, context_boost=0.35, window_before=30, window_after=0,
        context=["employee id", "emp id", "emp no", "employee no", "staff id", "member id",
                 "customer id", "patient id", "student id", "roll no", "id no", "id number",
                 "voter id", "epic", "uan", "pf no", "esic", "policy no", "mrn", "badge"],
    ),
    PatternRecognizer(
        "id_number", "ID_NUMBER",
        [B + r"\d{8,20}" + E],
        base=0.35, context=["no", "no.", "number", "id", "#", "identification"], context_boost=0.25,
        negative_context=_ID_NEG, negative_penalty=0.3,
    ),
    PatternRecognizer(
        "date", "DATE",
        [
            B + r"(?:0?[1-9]|[12]\d|3[01])[/\-.](?:0?[1-9]|1[0-2])[/\-.](?:19|20)\d{2}" + E,
            B + r"(?:0?[1-9]|1[0-2])[/\-.](?:0?[1-9]|[12]\d|3[01])[/\-.](?:19|20)\d{2}" + E,
            B + r"(?:19|20)\d{2}[/\-.](?:0?[1-9]|1[0-2])[/\-.](?:0?[1-9]|[12]\d|3[01])" + E,
            B + r"(?:the\s+)?(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTHS + r",?\s+(?:19|20)\d{2}" + E,
            B + _MONTHS + r"\.?\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}" + E,
        ],
        base=0.25, flags=re.I, context_type="DATE_OF_BIRTH", context_boost=0.65, window_before=50,
        context=["dob", "d.o.b", "date of birth", "birth date", "birthdate", "born", "birthday", "b'day"],
        negative_context=["invoice", "issue", "issued", "iss", "expiry", "exp", "valid", "due",
                          "dated", "order date", "bill date", "printed"],
        negative_penalty=0.2,
    ),
    PatternRecognizer(
        "postal_code", "POSTAL_CODE",
        [B + r"[1-9]\d{2}\s?\d{3}" + E, B + r"\d{5}(?:-\d{4})?" + E],
        base=0.4, require_context=True, context_boost=0.3, window_before=25, window_after=12,
        context=["pin", "pincode", "pin code", "postal", "postcode", "post code", "zip", "zip code"],
    ),
    PatternRecognizer(
        "street_address", "ADDRESS",
        [r"(?<![\w])\d{1,5}[A-Za-z]?(?:[ ,/\-]+[A-Za-z0-9][\w.'\-]*){0,5}?[ ,]+"
         r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd|court|ct|way|place|pl|"
         r"nagar|marg|colony|layout|cross|main road|sector|block|apartments?|apt|flat|floor|highway|"
         r"hwy|terrace|circle|parkway|pkwy|enclave|vihar|society|chowk|gali)\b\.?"],
        base=0.75, flags=re.I,
        context=["address", "residence", "lives at", "resides", "home"], context_boost=0.1,
    ),
    PatternRecognizer(
        "street_glued", "ADDRESS",          # OCR drops spaces: "8123MAINSTREET"
        [B + r"\d{1,5} ?[A-Za-z]{2,24}?(?:street|road|avenue|lane|drive|boulevard|nagar|marg)" + E],
        base=0.7, flags=re.I,
    ),
    PatternRecognizer(
        "unit", "ADDRESS",
        [B + r"(?:apt|apartment|unit|suite|ste|flat|house no|h\.? ?no|plot no|plot|door no|sector|block)\.? ?#? ?\d{1,5}[A-Z]?" + E],
        base=0.6, flags=re.I,
    ),
    PatternRecognizer(
        "city_state_zip", "ADDRESS",        # US: "HARRISBURG, PA 17101-0000", "ALBANY,NY-12222"
        [r"(?<![\w])[A-Z][A-Za-z .'\-]{1,30}, ?[A-Z]{2}[ ,\-]+\d{5}(?:-\d{4})?" + E],
        base=0.7,
    ),
    PatternRecognizer(
        "address_field", "ADDRESS",
        [B + r"(?i:(?:residential|permanent|home|street|mailing|postal|property|billing|shipping|current)?[ \t]*"
         r"(?:address|addr\.?|residence))[ \t]*\**[ \t]*[:|][ \t]*(?P<v>[^\n]{6,160})",
         B + r"(?i:resides at|resid(?:ing|e) at|lives at|living at|located at|domiciled at)[ \t]+(?P<v>[^\n]{6,160})"],
        base=0.88, postprocess=_trim_line, window_before=0, window_after=0,   # beats partial street matches
    ),
    PatternRecognizer(
        "street_number_after", "ADDRESS",     # "Khreshchatyk Street 34", "Jalan Sudirman No.34", "75 Yulgok-ro"
        [B + r"[A-Z][\w'\-]+(?: [A-Z][\w'\-]+){0,3} (?:Street|St|Avenue|Ave|Road|Rd|Lane|Boulevard|Blvd|Drive|"
         r"Way|Ulitsa|Vulytsia|Strasse|Straße|Gasse|Weg|Allee|Platz|Prospekt|Utca|Ulica|Caddesi|Sokak)\.?,? \d{1,5}[A-Za-z]?" + E,
         B + r"(?:Jalan|Jl\.|Calle|Rue|Via|Avenida|Rua|Calea|Strada) [A-Z][\w' ]{2,30}?,? (?:No\.? ?)?\d{1,5}[A-Za-z]?" + E,
         B + r"\d{1,5}(?:-\d{1,5})?,? [A-Z][a-z]+(?:-[a-z]+)?-(?:ro|gil|dong|daero)(?: \d{1,5}(?:-\d{1,5})?)?" + E],
        base=0.7,
    ),
    PatternRecognizer(
        "city_zip", "ADDRESS",                # "Pomona, 91766", "Louisville, Kentucky, 40202", "FL, 33161"
        [B + r"(?:[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}|[A-Z]{2}), (?:[A-Z][a-z]+(?: [A-Z][a-z]+)?, )?\d{5}(?:-\d{4})?" + E],
        base=0.6,
    ),
    PatternRecognizer(
        "credential_field", "CREDENTIAL",
        [B + r"(?i:(?P<k>user ?names?|login(?: id)?|user id|handle|passwords?|passwd|pwd|pass ?codes?|"
         r"api[ _-]?keys?|access keys?|secret(?: keys?)?|auth(?:entication)? tokens?|bearer tokens?|"
         r"session (?:id|token)|tokens?))"
         r"[ \t]*[\"'*]*[ \t]*(?:[:=|]|,|\bis\b|\bwas\b|\bof\b|\bset to\b|\bsuch as\b|\blike\b|\bas\b)?"
         r"(?:[ \t]+(?i:is|was|set to|such as|like|correctly set to))?[ \t]*[\"'*`(]*[ \t]*"
         r"(?P<v>[^\s`'\"|,;()]{3,256})"],
        base=0.85, postprocess=_credential, window_before=0, window_after=0,
    ),
    PatternRecognizer(
        "cookie", "CREDENTIAL",               # "user_session=jf4k7m9p2r; Path=/; HttpOnly; Secure"
        [B + r"[A-Za-z_][\w\-]{1,40}=[^;\s]{2,200}(?:; ?(?:Expires=[^;\n]{5,40}|Path=[^;\s]*|Domain=[^;\s]*|"
         r"Max-Age=\d+|HttpOnly|Secure|SameSite=\w+))+",
         B + r"[A-Za-z_][\w\-]{1,40}=[A-Za-z0-9%._\-]{6,200}" + E],
        base=0.5, context=["cookie", "set-cookie", "session"], context_boost=0.35, window_before=40,
        validator=lambda v: ";" in v, valid_score=0.85,
    ),
    PatternRecognizer(
        "uuid", "ID_NUMBER",
        [B + r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}" + E],
        base=0.7,
    ),
    PatternRecognizer(
        "api_key", "CREDENTIAL",
        [B + r"(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|gh[pousr]_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9\-]{10,}|"
         r"(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9_\-]{20,})" + E],
        base=0.95,
    ),
    PatternRecognizer(
        "secret_context", "CREDENTIAL",
        [B + r"[A-Za-z0-9_\-+/=]{24,}" + E],
        base=0.5, require_context=True, context_boost=0.35, window_before=40, window_after=0,
        validator=lambda v: bool(re.search(r"\d", v) and re.search(r"[A-Za-z]", v)), valid_score=0.5,
        context=["key", "token", "secret", "cookie", "password", "credential", "bearer"],
    ),
    PatternRecognizer(
        "mac", "DEVICE_ID",
        [B + r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}" + E],
        base=0.85,
    ),
    PatternRecognizer(
        "ipv6", "IP_ADDRESS",
        [r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"],
        base=0.3, validator=V.ipv6, valid_score=0.8,
    ),
    PatternRecognizer(
        "swift", "SWIFT_BIC",
        [B + r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?" + E],
        base=0.45, require_context=True, context_boost=0.4, window_before=30, window_after=0,
        context=["swift", "bic", "swift code", "bic code", "swift bic", "swift/bic"],
    ),
    PatternRecognizer(
        "plate", "VEHICLE_ID",
        [B + r"[A-Z]{2}[ \-]?\d{1,2}[ \-]?[A-Z]{1,3}[ \-]?\d{4}" + E,            # India: MH 12 AB 1234
         B + r"[A-Z0-9]{1,4}[ \-]?[A-Z0-9]{1,4}(?:[ \-]?[A-Z0-9]{1,4})?" + E],
        base=0.4, require_context=True, context_boost=0.45, window_before=30, window_after=0,
        validator=lambda v: bool(re.search(r"\d", v) and re.search(r"[A-Z]", v)), valid_score=0.4,
        context=["license plate", "licence plate", "number plate", "plate", "plate number", "plate no",
                 "registration number", "registration no", "reg no", "vehicle number", "vehicle no"],
    ),
    PatternRecognizer(
        "vin", "VEHICLE_ID",
        [B + r"[A-HJ-NPR-Z0-9]{17}" + E],
        base=0.45, validator=lambda v: sum(c.isdigit() for c in v) >= 3 and sum(c.isalpha() for c in v) >= 3,
        valid_score=0.6, context=["vin", "vehicle identification", "vehicle identifier", "chassis"],
        context_boost=0.3,
    ),
    PatternRecognizer(
        "coordinates", "LOCATION",
        [B + r"-?\d{1,2}\.\d{3,}°?,? ?[NS]?,? ?-?\d{1,3}\.\d{3,}°? ?[EW]?" + E],
        base=0.75,
    ),
    PatternRecognizer(
        "labelled_id", "GOV_ID",              # any form field whose label ends in ID / number / no.
        [B + r"(?i:(?:[a-z][a-z/&\-]*[ \t_]){0,4}(?:identifier|number|num|code|no\.|no|id|#)(?![A-Za-z]))"
         r"[ \t]*[\"'*]*[ \t]*(?:[:#|=]|\bis\b|\bof\b|\bnumbered\b|\bending in\b)?[ \t]*[\"'*]*[ \t]*"
         r"(?P<v>[A-Za-z0-9][A-Za-z0-9\-/.=]{3,78}[A-Za-z0-9=])" + E],
        base=0.62, postprocess=_id_value, window_before=40, window_after=0,
        negative_context=_ID_NEG + ["claim", "case", "ticket", "page", "version", "room", "flight",
                                    "table", "figure", "step", "phone", "fax", "mobile", "zip", "postal"],
        negative_penalty=0.45,
    ),
    PatternRecognizer(
        "name_field", "PERSON",
        # label is case-insensitive; the name itself must be Capitalised or ALL CAPS
        [
            # form fields: "**First Name:** Lois", "| Last Name | Sharp |", "Customer: Priya Sharma"
            B + r"(?i:full name|first name|last name|surname|given name|middle name|name on card|"
            r"(?:customer|client|patient|employee|contact|applicant|candidate|beneficiary|insured|"
            r"policy ?holder|account ?holder|card ?holder|owner|tenant|borrower|student|member|participant|"
            r"observer|witness|signatory|recipient|sender)(?: name)?|name|nominee|guardian|spouse|"
            r"next of kin|emergency contact|father'?s name|mother'?s name)"
            r"[ \t]*\**[ \t]*[:|][ \t]*\**[ \t]*" + NAME_VALUE,
            # salutations, titles and relations: "Dear Ravi", "Dr. Meera Nair", "S/O Ramesh"
            B + r"(?i:mr|mrs|ms|miss|dr|shri|smt|prof|dear|attn|s/o|d/o|w/o|c/o|son of|daughter of|wife of|"
            r"signed by|regards|sincerely|my name is|name is)(?![A-Za-z])\.?[ \t]*[:,\-]?[ \t]*" + NAME_VALUE,
        ],
        base=0.85, postprocess=_trim_name, window_before=0, window_after=0,
    ),
]

# Words that, if present anywhere in a document, indicate an identity document.
ID_DOCUMENT_TERMS = _term_regex([
    "driver license", "driver's license", "driving licence", "driving license", "dl no", "dln",
    "passport", "aadhaar", "aadhar", "uidai", "permanent account number", "income tax department",
    "date of birth", "dob", "aamva", "ssn", "social security", "voter", "election commission",
    "identity card", "id card", "national id", "government of india", "republic of",
])
ID_DOC_BOOST_TYPES = {"ID_NUMBER", "DRIVER_LICENSE", "PASSPORT", "AADHAAR", "GOV_ID"}
