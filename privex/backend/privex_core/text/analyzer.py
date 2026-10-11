"""
Text analyzer: runs all recognizers, applies document-level context,
resolves overlaps and propagates confirmed values.
"""

from __future__ import annotations

import re

from privex_core.config import settings
from privex_core.entities import Entity
from privex_core.text import ner
from privex_core.text.recognizers import (
    ID_DOC_BOOST_TYPES, ID_DOCUMENT_TERMS, RECOGNIZERS, PatternRecognizer,
)

MIN_SCORE = 0.2          # candidates below this are discarded entirely
ID_DOC_BOOST = 0.2


class Analyzer:
    def __init__(self, recognizers: list[PatternRecognizer] | None = None,
                 use_ner: bool | None = None, threshold: float | None = None):
        self.recognizers = RECOGNIZERS if recognizers is None else recognizers
        self.use_ner = settings.use_ner if use_ner is None else use_ner
        self.threshold = settings.threshold if threshold is None else threshold

    def analyze(self, text: str) -> list[Entity]:
        if not text or not text.strip():
            return []

        candidates: list[Entity] = []
        for r in self.recognizers:
            candidates.extend(r.analyze(text))
        if self.use_ner:
            candidates.extend(ner.analyze(text))
            candidates.extend(ner.gazetteer_names(text))

        # Document-level context: identity documents make bare ID-like values sensitive.
        id_doc = ID_DOCUMENT_TERMS.search(text)
        if id_doc:
            if self.use_ner:
                candidates.extend(ner.caps_name_lines(text))
            for c in candidates:
                if c.type in ID_DOC_BOOST_TYPES:
                    c.score = min(1.0, c.score + ID_DOC_BOOST)
                    c.reasons.append(f"document looks like an ID ('{id_doc.group(0)}')")

        candidates = [c for c in candidates if c.score >= MIN_SCORE]
        resolved = _resolve_overlaps(candidates)
        resolved = _propagate(text, resolved, self.threshold)
        return sorted(resolved, key=lambda e: e.start)

    def redact(self, text: str, entities: list[Entity] | None = None, style: str = "mask") -> str:
        """style: 'mask' (█████) or 'tag' ([PHONE])."""
        if entities is None:
            entities = self.analyze(text)
        out, last = [], 0
        for e in sorted((e for e in entities if e.score >= self.threshold), key=lambda e: e.start):
            if e.start < last:
                continue
            out.append(text[last:e.start])
            out.append(f"[{e.type}]" if style == "tag" else "█" * (e.end - e.start))
            last = e.end
        out.append(text[last:])
        return "".join(out)

    def scan(self, text: str, style: str = "mask") -> dict:
        entities = self.analyze(text)
        sensitive = [e for e in entities if e.score >= self.threshold]
        return {
            "sensitive": bool(sensitive),
            "entity_count": len(sensitive),
            "entities": [e.to_dict(self.threshold) for e in entities],
            "redacted_text": self.redact(text, entities, style),
            "threshold": self.threshold,
        }


def _resolve_overlaps(cands: list[Entity]) -> list[Entity]:
    """Greedy: highest score first, then longest span. Overlapping losers are dropped."""
    chosen: list[Entity] = []
    for c in sorted(cands, key=lambda e: (-e.score, -(e.end - e.start), e.start)):
        if not any(c.overlaps(k) for k in chosen):
            chosen.append(c)
    return chosen


def _propagate(text: str, ents: list[Entity], threshold: float) -> list[Entity]:
    """A value confirmed sensitive once is sensitive everywhere it appears."""
    out = list(ents)
    for e in ents:
        if e.score < threshold or sum(c.isalnum() for c in e.text) < 3:
            continue
        for m in re.finditer(rf"(?<!\w){re.escape(e.text)}(?!\w)", text):
            cand = Entity(e.type, e.text, m.start(), m.end(), e.score, e.source + "+propagated",
                          ["repeats a value detected elsewhere in the document"])
            if not any(cand.overlaps(o) for o in out):
                out.append(cand)
            else:
                # upgrade a weaker overlapping candidate with the identical span
                for i, o in enumerate(out):
                    if o.start == cand.start and o.end == cand.end and o.score < cand.score:
                        out[i] = cand
    return out


_default: Analyzer | None = None


def default_analyzer() -> Analyzer:
    global _default
    if _default is None:
        _default = Analyzer()
    return _default
