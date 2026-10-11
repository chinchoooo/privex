"""
Loaders for public PII benchmarks → PRIVEX eval rows:

    {"text": str, "entities": [{"start", "end", "label", "type", "scope"}], "meta": {...}}

  label  original dataset label
  type   closest PRIVEX entity type (None if PRIVEX has no equivalent)
  scope  "direct"  – identifies a person on its own; leaving it visible is a leak
         "quasi"   – attribute / indirect identifier; reported, but redacting it is not penalised
         "ignore"  – annotated as not-to-mask; redacting it counts as over-redaction

Download (files land in eval/data/, which is git-ignored):
    python -m eval.datasets nemotron
    python -m eval.datasets tab
"""

from __future__ import annotations

import ast
import json
import random
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

# ── Nemotron-PII (nvidia, CC BY 4.0) ───────────────────────────────────────────
# https://huggingface.co/datasets/nvidia/Nemotron-PII — synthetic, 55 labels, US + intl locales,
# structured (forms) and unstructured documents.

NEMOTRON_DIRECT = {
    "first_name": "PERSON", "last_name": "PERSON", "email": "EMAIL", "phone_number": "PHONE",
    "fax_number": "PHONE", "street_address": "ADDRESS", "postcode": "POSTAL_CODE",
    "date_of_birth": "DATE_OF_BIRTH", "credit_debit_card": "CREDIT_CARD", "cvv": "CVV", "ssn": "SSN",
    "account_number": "BANK_ACCOUNT", "bank_routing_number": "BANK_ACCOUNT", "pin": "OTP",
    "customer_id": "GOV_ID", "employee_id": "GOV_ID", "medical_record_number": "GOV_ID",
    "health_plan_beneficiary_number": "GOV_ID", "certificate_license_number": "DRIVER_LICENSE",
    "tax_id": "GOV_ID", "unique_id": "ID_NUMBER", "ipv4": "IP_ADDRESS",
    "user_name": "CREDENTIAL", "password": "CREDENTIAL", "api_key": "CREDENTIAL",
    "http_cookie": "CREDENTIAL", "ipv6": "IP_ADDRESS", "mac_address": "DEVICE_ID",
    "device_identifier": "DEVICE_ID", "vehicle_identifier": "VEHICLE_ID", "license_plate": "VEHICLE_ID",
    "biometric_identifier": "GOV_ID", "swift_bic": "BANK_ACCOUNT", "coordinate": "LOCATION",
}
NEMOTRON_QUASI = {
    "date": "DATE", "time": None, "date_time": "DATE", "company_name": None, "occupation": None,
    "state": "LOCATION", "country": "LOCATION", "city": "LOCATION", "county": "LOCATION",
    "employment_status": None, "education_level": None, "age": None, "race_ethnicity": None,
    "gender": None, "language": None, "religious_belief": None, "political_view": None,
    "blood_type": None, "sexuality": None,
    # Nemotron labels every URL as PII, but most are company/resource links, not personal identifiers.
    "url": None,
}


def _nemotron_file() -> Path:
    return DATA / "nemotron" / "data" / "test-00000-of-00001.parquet"


def download_nemotron() -> Path:
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download("nvidia/Nemotron-PII", "data/test-00000-of-00001.parquet",
                                repo_type="dataset", local_dir=DATA / "nemotron"))


def split_of(uid: str) -> str:
    """Deterministic 50/50 split by record id: tune on 'dev', report on 'heldout'."""
    import hashlib
    return "dev" if hashlib.sha1(uid.encode()).digest()[0] % 2 == 0 else "heldout"


def load_nemotron(limit: int | None = 2000, seed: int = 0, locale: str | None = None,
                  fmt: str | None = None, split: str | None = "heldout") -> list[dict]:
    import pyarrow.parquet as pq
    path = _nemotron_file()
    if not path.exists():
        sys.exit("Nemotron-PII not downloaded: python -m eval.datasets nemotron")
    rows = pq.read_table(path).to_pylist()
    if split:
        rows = [r for r in rows if split_of(r["uid"]) == split]
    if locale:
        rows = [r for r in rows if r["locale"] == locale]
    if fmt:
        rows = [r for r in rows if r["document_format"] == fmt]
    if limit and limit < len(rows):
        rows = random.Random(seed).sample(rows, limit)
    out = []
    for r in rows:
        ents = []
        for s in ast.literal_eval(r["spans"]):
            lab = s["label"]
            if lab in NEMOTRON_DIRECT:
                scope, typ = "direct", NEMOTRON_DIRECT[lab]
            else:
                scope, typ = "quasi", NEMOTRON_QUASI.get(lab)
            ents.append({"start": s["start"], "end": s["end"], "label": lab, "type": typ, "scope": scope})
        out.append({"text": r["text"], "entities": ents,
                    "meta": {"id": r["uid"], "locale": r["locale"], "format": r["document_format"],
                             "doc_type": r["document_type"]}})
    return out


# ── TAB: Text Anonymization Benchmark (Norsk Regnesentral, MIT) ───────────────
# https://github.com/NorskRegnesentral/text-anonymization-benchmark — real ECHR court cases,
# manually annotated with DIRECT / QUASI / NO_MASK identifier decisions.

TAB_TYPE = {"PERSON": "PERSON", "CODE": "ID_NUMBER", "LOC": "LOCATION", "DATETIME": "DATE",
            "ORG": None, "DEM": None, "QUANTITY": None, "MISC": None}
TAB_SCOPE = {"DIRECT": "direct", "QUASI": "quasi", "NO_MASK": "ignore"}
TAB_URL = "https://raw.githubusercontent.com/NorskRegnesentral/text-anonymization-benchmark/master/echr_{}.json"


def download_tab(split: str = "test") -> Path:
    import urllib.request
    dest = DATA / "tab" / f"echr_{split}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(TAB_URL.format(split), dest)
    return dest


def load_tab(split: str = "test", limit: int | None = None) -> list[dict]:
    path = DATA / "tab" / f"echr_{split}.json"
    if not path.exists():
        sys.exit("TAB not downloaded: python -m eval.datasets tab")
    docs = json.loads(path.read_text(encoding="utf-8"))[:limit]
    out = []
    for d in docs:
        # first annotator only (some documents have several)
        ann = d["annotations"][sorted(d["annotations"])[0]]["entity_mentions"]
        ents = [{"start": m["start_offset"], "end": m["end_offset"],
                 "label": f'{m["entity_type"]}/{m["identifier_type"]}',
                 "type": TAB_TYPE.get(m["entity_type"]), "scope": TAB_SCOPE[m["identifier_type"]]}
                for m in ann]
        out.append({"text": d["text"], "entities": ents, "meta": {"id": d["doc_id"]}})
    return out


def _trust_system_certs():
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


if __name__ == "__main__":
    _trust_system_certs()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("nemotron", "all"):
        print("ok", download_nemotron())
    if which in ("tab", "all"):
        print("ok", download_tab("test"))
