"""
Statistical NER for names and locations (spaCy, CPU, ~12 MB model).

OCR of ID cards is often ALL CAPS, which spaCy's small model handles poorly.
We feed it a length-preserving case-normalised copy of the text so character
offsets stay identical to the original.
"""

from __future__ import annotations

import gzip
import logging
import re
import threading
from pathlib import Path

from privex_core.config import settings
from privex_core.entities import Entity

log = logging.getLogger(__name__)

_nlp = None
_lock = threading.Lock()
_unavailable = False

# All-caps tokens that should stay as-is (acronyms / field labels).
_KEEP_UPPER = {
    "DOB", "DL", "DLN", "ID", "PAN", "SSN", "USA", "UK", "UAE", "IFSC", "UPI", "OTP", "CVV",
    "PIN", "AADHAAR", "UIDAI", "GOVT", "INDIA", "HD", "NO", "SEX", "EXP", "ISS", "CLASS", "DD",
    "REST", "END", "M", "F", "VISA", "ATM", "PVT", "LTD", "LLC", "INC", "SBI", "HDFC", "ICICI",
}

# Words that indicate a "PERSON" span is actually a document header / org.
_NOT_PERSON = re.compile(
    r"\b(license|licence|card|government|republic|department|bank|india|state|driver|driving|"
    r"passport|identity|authority|ministry|income|tax|date|birth|signature|address|class|"
    r"motor|vehicle|commission|university|limited|ltd|pvt|inc|corp|hospital|school|college|"
    r"beneficiary|customer|item|sku|order|invoice|account|payment|email|e-mail|phone|mobile|"
    r"aadhaar|aadhar|pan|name|dob|address|ifsc|upi|otp|cvv|ssn)\b",
    re.I,
)


def _normalise_case(text: str) -> str:
    def fix(m: re.Match) -> str:
        w = m.group(0)
        return w if w in _KEEP_UPPER else w.capitalize()
    return re.sub(r"\b[A-Z]{2,}\b", fix, text)


_DATA = Path(__file__).with_name("data")
_lexicons: tuple[frozenset, frozenset] | None = None


def _lex() -> tuple[frozenset, frozenset]:
    """(known given names + surnames, common English words) — see scripts/build_lexicons.py."""
    global _lexicons
    if _lexicons is None:
        def read(name):
            try:
                with gzip.open(_DATA / name, "rt", encoding="utf-8") as f:
                    return frozenset(f.read().split())
            except OSError:
                return frozenset()
        _lexicons = (read("names.txt.gz"), read("common_en.txt.gz"))
    return _lexicons


def plausible_name(value: str) -> bool:
    """
    Reject NER 'names' made only of ordinary words ("Maintenance Schedule", "Generate") and short
    acronyms ("HIPAA"); keep anything containing a known name or an unknown (often foreign) word.
    """
    names, common = _lex()
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", value)
    if not words:
        return False
    if len(words) == 1 and words[0].isupper() and len(words[0]) <= 6 and words[0].lower() not in names:
        return False
    low = [w.lower().strip("'-") for w in words]
    if any(w in names for w in low):
        return True
    return not all(w in common for w in low)


_CAP_WORD = r"[A-Z][A-Za-z.'\-]+"
_EXPAND_STOP = re.compile(r"^(?:Mr|Mrs|Ms|Dr|Shri|Smt|The|And|Of|In|At|On|To|From|Dear|Name|Dob|Date|Address)\.?$", re.I)


def _expand(text: str, start: int, end: int, max_tokens: int = 4) -> tuple[int, int]:
    """Grow a PERSON span over adjacent capitalised words on the same line."""
    while len(text[start:end].split()) < max_tokens:
        m = re.search(rf"({_CAP_WORD})[ \t]+$", text[:start])
        if not m or _EXPAND_STOP.match(m.group(1)) or _NOT_PERSON.search(m.group(1)) \
                or not plausible_name(m.group(1)):
            break
        start = m.start(1)
    while len(text[start:end].split()) < max_tokens:
        m = re.match(rf"[ \t]+({_CAP_WORD})", text[end:])
        if not m or _EXPAND_STOP.match(m.group(1)) or _NOT_PERSON.search(m.group(1)) \
                or not plausible_name(m.group(1)):
            break
        end += m.end(1)
    return start, end


def caps_name_lines(text: str) -> list[Entity]:
    """On ID documents, a line of 2-4 ALL-CAPS alphabetic words is very often the holder's name."""
    out = []
    for m in re.finditer(r"(?m)^[ \t]*((?:[A-Z][A-Z.'\-]+[ \t]+){1,3}[A-Z][A-Z.'\-]+)[ \t]*$", text):
        value = m.group(1)
        words = value.split()
        if _NOT_PERSON.search(value) or any(w in _KEEP_UPPER for w in words if len(w) > 2) \
                or not plausible_name(value):
            continue
        out.append(Entity("PERSON", value, m.start(1), m.end(1), 0.65, "heuristic:caps-line",
                          ["all-caps line of words on an identity document"]))
    return out


_CAP_SEQ = re.compile(r"\b[A-Z][a-z][A-Za-z'\-]*(?:[ \t]+[A-Z][a-z][A-Za-z'\-]*){1,3}\b")


def gazetteer_names(text: str) -> list[Entity]:
    """
    2-4 capitalised words containing a known given name / surname ("Contact Kavya Smith on…").
    Leading/trailing ordinary words that are not names are trimmed ("Contact", "Employee").
    """
    names, common = _lex()
    out = []
    for m in _CAP_SEQ.finditer(text):
        toks = list(re.finditer(r"\S+", m.group(0)))
        low = [t.group(0).lower() for t in toks]
        i, j = 0, len(toks)
        while i < j and low[i] in common and low[i] not in names:
            i += 1
        while j > i and low[j - 1] in common and low[j - 1] not in names:
            j -= 1
        if j - i < 2 or not any(w in names for w in low[i:j]):
            continue
        s0, e0 = m.start() + toks[i].start(), m.start() + toks[j - 1].end()
        value = text[s0:e0]
        if _NOT_PERSON.search(value):
            continue
        out.append(Entity("PERSON", value, s0, e0, 0.7, "lexicon:names",
                          ["capitalised words including a known first name / surname"]))
    return out


def load():
    global _nlp, _unavailable
    if _nlp is not None or _unavailable:
        return _nlp
    with _lock:
        if _nlp is None and not _unavailable:
            try:
                import spacy
                _nlp = spacy.load(settings.spacy_model,
                                  exclude=["parser", "lemmatizer", "attribute_ruler", "tagger", "senter"])
                log.info("Loaded spaCy model %s", settings.spacy_model)
            except Exception as e:      # model missing → regex-only mode
                log.warning("spaCy NER unavailable (%s); continuing with pattern recognizers only", e)
                _unavailable = True
    return _nlp


def is_available() -> bool:
    return load() is not None


def analyze(text: str) -> list[Entity]:
    nlp = load()
    if nlp is None or not text.strip():
        return []
    doc = nlp(_normalise_case(text))
    out: list[Entity] = []
    for ent in doc.ents:
        value = text[ent.start_char:ent.end_char]
        if ent.label_ == "PERSON":
            s0, e0 = ent.start_char, ent.end_char
            if "\n" in text[s0:e0]:                      # never let a name span lines
                e0 = s0 + text[s0:e0].index("\n")
            s0, e0 = _expand(text, s0, e0)
            value = text[s0:e0]
            if _NOT_PERSON.search(value) or re.search(r"\d", value) or not re.search(r"[A-Za-z]{2}", value) \
                    or not plausible_name(value):
                continue
            tokens = len(value.split())
            score = 0.8 if tokens >= 2 else 0.6
            out.append(Entity("PERSON", value, s0, e0, score, "ner:spacy",
                              [f"spaCy NER tagged PERSON ({tokens} token{'s' if tokens > 1 else ''})"]))
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            out.append(Entity("LOCATION", value, ent.start_char, ent.end_char, 0.4, "ner:spacy",
                              [f"spaCy NER tagged {ent.label_}; locations alone are low risk"]))
    return out
