"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


# Canonical entity types and human-readable labels.
LABELS: dict[str, str] = {
    "PERSON": "Full Name",
    "EMAIL": "Email Address",
    "PHONE": "Phone Number",
    "CREDIT_CARD": "Credit/Debit Card",
    "CVV": "CVV",
    "BANK_ACCOUNT": "Bank Account Number",
    "IBAN": "IBAN",
    "IFSC": "IFSC Code",
    "UPI": "UPI ID",
    "AADHAAR": "Aadhaar Number",
    "PAN": "PAN",
    "SSN": "US SSN",
    "PASSPORT": "Passport Number",
    "DRIVER_LICENSE": "Driving License",
    "GOV_ID": "Government / Employee ID",
    "DATE_OF_BIRTH": "Date of Birth",
    "DATE": "Date",
    "ADDRESS": "Address",
    "LOCATION": "Location",
    "POSTAL_CODE": "Postal Code",
    "OTP": "OTP / PIN",
    "IP_ADDRESS": "IP Address",
    "ID_NUMBER": "ID / Account-like Number",
    "CREDENTIAL": "Username / Password / Secret",
    "DEVICE_ID": "Device Identifier",
    "VEHICLE_ID": "Vehicle Plate / VIN",
    "SWIFT_BIC": "SWIFT / BIC Code",
}


@dataclass
class Entity:
    type: str
    text: str
    start: int
    end: int
    score: float
    source: str                     # recognizer name, e.g. "regex:credit_card", "ner:spacy"
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.type, self.type.title())

    def overlaps(self, other: "Entity") -> bool:
        return self.start < other.end and other.start < self.end

    def to_dict(self, threshold: float) -> dict:
        d = asdict(self)
        d["label"] = self.label
        d["score"] = round(self.score, 3)
        d["sensitive"] = self.score >= threshold
        d["reason"] = "; ".join(self.reasons)
        return d
