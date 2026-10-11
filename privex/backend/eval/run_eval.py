"""
Evaluate the text analyzer.

    python -m eval.run_eval                                  # synthetic dev set (generated)
    python -m eval.run_eval --dataset nemotron --limit 3000  # NVIDIA Nemotron-PII (held-out)
    python -m eval.run_eval --dataset tab                    # TAB — real ECHR court cases
    python -m eval.run_eval --data my_set.jsonl              # your own {"text","entities"} JSONL
    options: --threshold 0.6  --no-ner  --errors 20  --json out.json  --locale us|intl  --format structured

Gold spans carry a scope (see eval/datasets.py): "direct" identifiers must be hidden, "quasi"
identifiers are reported but not penalised, "ignore" spans were judged safe to show.

Metrics (all untyped — for a redaction tool what matters is whether the characters are hidden):
  leak rate          share of direct-identifier characters left visible
  span recall        direct spans with ≥ 50 % of their characters hidden
  span precision     predicted spans that overlap any direct/quasi gold span
  over-redaction     share of non-identifier characters that were hidden
  per-label recall   for every gold label (shows which identifier kinds are missed)
  per-type precision for every PRIVEX type (shows which recognizers over-fire)
Typed P/R/F1 is also reported when gold spans have PRIVEX types (synthetic data).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict

from privex_core.text.analyzer import Analyzer

# Predicted types accepted for a gold type in the typed metric.
EQUIV = {
    "DATE_OF_BIRTH": {"DATE_OF_BIRTH", "DATE"},
    "BANK_ACCOUNT": {"BANK_ACCOUNT", "ID_NUMBER", "GOV_ID"},
    "ADDRESS": {"ADDRESS", "LOCATION", "POSTAL_CODE"},
    "POSTAL_CODE": {"POSTAL_CODE", "ADDRESS"},
    "GOV_ID": {"GOV_ID", "ID_NUMBER", "BANK_ACCOUNT", "DRIVER_LICENSE", "PASSPORT"},
    "ID_NUMBER": {"ID_NUMBER", "GOV_ID", "BANK_ACCOUNT", "DRIVER_LICENSE", "PASSPORT"},
    "DRIVER_LICENSE": {"DRIVER_LICENSE", "ID_NUMBER", "GOV_ID"},
    "OTP": {"OTP", "CVV", "ID_NUMBER"},
}


def _coverage(mask: list[bool], text: str, s: int, e: int) -> tuple[int, int]:
    """(hidden, total) non-space characters in text[s:e]."""
    tot = hid = 0
    for k in range(s, min(e, len(text))):
        if not text[k].isspace():
            tot += 1
            hid += mask[k]
    return hid, tot


def evaluate(rows: list[dict], analyzer: Analyzer, show_errors: int = 0, seed: int = 0,
             only_label: str | None = None) -> dict:
    lab_n, lab_hit = defaultdict(int), defaultdict(int)
    type_n, type_tp = defaultdict(int), defaultdict(int)
    typed_tp, typed_fn = defaultdict(int), defaultdict(int)
    direct_chars = direct_hidden = quasi_chars = quasi_hidden = clean_chars = clean_hidden = 0
    d_spans = d_hit = n_pred = n_pred_tp = 0
    misses, false_pos = [], []
    t0 = time.perf_counter()

    for row in rows:
        text = row["text"]
        gold = [dict(g, scope=g.get("scope", "direct"), label=g.get("label", g.get("type"))) for g in row["entities"]]
        preds = [e for e in analyzer.analyze(text) if e.score >= analyzer.threshold]

        mask = [False] * len(text)
        for p in preds:
            for k in range(p.start, min(p.end, len(text))):
                mask[k] = True
        in_gold = [False] * len(text)
        for g in gold:
            if g["scope"] != "ignore":
                for k in range(g["start"], min(g["end"], len(text))):
                    in_gold[k] = True

        for g in gold:
            hid, tot = _coverage(mask, text, g["start"], g["end"])
            if not tot:
                continue
            hit = hid >= 0.5 * tot
            lab_n[g["label"]] += 1; lab_hit[g["label"]] += hit
            if g["scope"] == "direct":
                direct_chars += tot; direct_hidden += hid
                d_spans += 1; d_hit += hit
                if not hit and (only_label is None or g["label"] == only_label):
                    misses.append((g["label"], text[g["start"]:g["end"]],
                                   text[max(0, g["start"] - 60):g["end"] + 60]))
            elif g["scope"] == "quasi":
                quasi_chars += tot; quasi_hidden += hid
            if g.get("type") and g["scope"] == "direct":
                ok = EQUIV.get(g["type"], {g["type"]})
                if any(p.type in ok and _coverage([True] * len(text), text, max(p.start, g["start"]),
                                                   min(p.end, g["end"]))[1] >= 0.5 * tot for p in preds):
                    typed_tp[g["type"]] += 1
                else:
                    typed_fn[g["type"]] += 1

        for p in preds:
            n_pred += 1; type_n[p.type] += 1
            tp = any(in_gold[k] for k in range(p.start, min(p.end, len(text))))
            n_pred_tp += tp; type_tp[p.type] += tp
            if not tp:
                false_pos.append((p.type, p.text, "; ".join(p.reasons), text[max(0, p.start - 60):p.end + 60]))

        for k, ch in enumerate(text):
            if not ch.isspace() and not in_gold[k]:
                clean_chars += 1; clean_hidden += mask[k]

    elapsed = time.perf_counter() - t0
    rec = d_hit / d_spans if d_spans else 1.0
    prec = n_pred_tp / n_pred if n_pred else 1.0
    rnd = random.Random(seed)
    return {
        "n_docs": len(rows),
        "ms_per_doc": 1000 * elapsed / max(1, len(rows)),
        "leak_rate": 1 - direct_hidden / direct_chars if direct_chars else 0.0,
        "span_recall": rec,
        "span_precision": prec,
        "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "quasi_hidden": quasi_hidden / quasi_chars if quasi_chars else None,
        "over_redaction": clean_hidden / clean_chars if clean_chars else 0.0,
        "per_label_recall": {l: {"n": lab_n[l], "recall": lab_hit[l] / lab_n[l]} for l in lab_n},
        "per_type_precision": {t: {"n": type_n[t], "precision": type_tp[t] / type_n[t]} for t in type_n},
        "typed_recall": {t: {"n": typed_tp[t] + typed_fn[t], "recall": typed_tp[t] / (typed_tp[t] + typed_fn[t])}
                         for t in set(typed_tp) | set(typed_fn)},
        "misses": rnd.sample(misses, min(show_errors, len(misses))),
        "false_positives": rnd.sample(false_pos, min(show_errors, len(false_pos))),
    }


def _snip(value: str, text: str, width: int = 50) -> str:
    i = text.find(value)
    s = text[max(0, i - width // 2): i + len(value) + width // 2] if i >= 0 else text[:width]
    return s.replace("\n", " ⏎ ")


def print_report(res: dict, scopes: dict[str, str] | None = None) -> None:
    print(f"\nDocs: {res['n_docs']}   {res['ms_per_doc']:.1f} ms/doc")
    print(f"Direct identifiers  leak {res['leak_rate']:.1%} of characters   "
          f"span recall {res['span_recall']:.3f}   span precision {res['span_precision']:.3f}   F1 {res['f1']:.3f}")
    if res["quasi_hidden"] is not None:
        print(f"Quasi identifiers   {res['quasi_hidden']:.1%} of characters hidden (not penalised)")
    print(f"Over-redaction      {res['over_redaction']:.1%} of non-identifier characters hidden\n")

    print(f"{'gold label':34} {'scope':6} {'n':>6} {'recall':>7}")
    for lab, s in sorted(res["per_label_recall"].items(), key=lambda x: (scopes or {}).get(x[0], "") + f"{x[1]['recall']:.3f}"):
        print(f"{lab:34} {(scopes or {}).get(lab, ''):6} {s['n']:6} {s['recall']:7.3f}")

    print(f"\n{'PRIVEX type':18} {'n':>6} {'precision':>9}")
    for t, s in sorted(res["per_type_precision"].items(), key=lambda x: x[1]["precision"]):
        print(f"{t:18} {s['n']:6} {s['precision']:9.3f}")

    if res["misses"]:
        print("\nSample misses (direct identifiers left visible):")
        for lab, val, text in res["misses"]:
            print(f"  {lab:28} {val!r:32} …{_snip(val, text)}…")
    if res["false_positives"]:
        print("\nSample false positives (redacted, not an identifier):")
        for t, val, why, text in res["false_positives"]:
            print(f"  {t:14} {val!r:28} [{why[:60]}] …{_snip(val, text)}…")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["synth", "nemotron", "tab"], default="synth")
    ap.add_argument("--data", help="JSONL file of {text, entities:[{start,end,type|label,scope?}]}")
    ap.add_argument("--n", type=int, default=500, help="synthetic: number of docs")
    ap.add_argument("--limit", type=int, default=2000, help="nemotron: sample size (0 = all 100k)")
    ap.add_argument("--split", choices=["dev", "heldout", "all"], default="heldout",
                    help="nemotron: tune on dev, report on heldout")
    ap.add_argument("--label", help="only show misses for this gold label")
    ap.add_argument("--locale", choices=["us", "intl"])
    ap.add_argument("--format", choices=["structured", "unstructured"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--no-ner", action="store_true")
    ap.add_argument("--errors", type=int, default=15)
    ap.add_argument("--json", help="also write full results to this file")
    a = ap.parse_args()

    if a.data:
        with open(a.data, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
    elif a.dataset == "nemotron":
        from eval.datasets import load_nemotron
        rows = load_nemotron(a.limit or None, a.seed, a.locale, a.format,
                             None if a.split == "all" else a.split)
    elif a.dataset == "tab":
        from eval.datasets import load_tab
        rows = load_tab("test")
    else:
        from eval.synth import generate
        rows = generate(a.n, a.seed)

    scopes = {}
    for r in rows:
        for g in r["entities"]:
            scopes.setdefault(g.get("label", g.get("type")), g.get("scope", "direct"))

    analyzer = Analyzer(use_ner=not a.no_ner, threshold=a.threshold)
    res = evaluate(rows, analyzer, a.errors, a.seed, only_label=a.label)
    print_report(res, scopes)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
