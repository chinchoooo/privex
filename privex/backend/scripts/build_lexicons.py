"""
Build the small lexicons shipped in privex_core/text/data/ (run once; outputs are committed).

  names.txt.gz      given names + common surnames — used to *rescue* real names that are also
                    ordinary words ("Grace", "Mark", "Brown")
  common_en.txt.gz  frequent English words — a NER "PERSON" whose every token is a common word
                    and none is a known name ("Maintenance Schedule", "Generate") is rejected

Sources (all redistributable):
  • US Census 2010 surnames (public domain) — census.gov/topics/genealogy/2010surnames
  • NLTK names corpus, © 1991 Mark Kantrowitz, "freely redistributable"
  • dominictarr/random-name first-names.txt (MIT)
  • wordfreq 3.x English frequencies (Apache-2.0; wordfreq data CC BY-SA 4.0) — dev-only dependency

    pip install wordfreq
    python scripts/build_lexicons.py eval/data/lex
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "privex_core" / "text" / "data"
SURNAME_MIN_COUNT = 2000      # ~10k most common US surnames
COMMON_MIN_ZIPF = 3.0         # roughly the 30k most frequent English words


def main(src: Path):
    names: set[str] = set()
    with zipfile.ZipFile(src / "census.zip") as z:
        with z.open("Names_2010Census.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                if row["name"] != "ALL OTHER NAMES" and row["count"].isdigit() and int(row["count"]) >= SURNAME_MIN_COUNT:
                    names.add(row["name"].lower())
    with zipfile.ZipFile(src / "nltk_names.zip") as z:
        for member in ("names/male.txt", "names/female.txt"):
            names |= {l.strip().lower() for l in z.read(member).decode("latin-1").splitlines() if l.strip()}
    names |= {l.strip().lower() for l in (src / "first-names.txt").read_text(encoding="utf-8").split() if l.strip()}
    names = {n for n in names if n.isalpha() and len(n) > 1}

    from wordfreq import top_n_list, zipf_frequency
    common = {w for w in top_n_list("en", 60000) if w.isalpha() and zipf_frequency(w, "en") >= COMMON_MIN_ZIPF}

    OUT.mkdir(parents=True, exist_ok=True)
    for fname, words in (("names.txt.gz", names), ("common_en.txt.gz", common)):
        with gzip.open(OUT / fname, "wt", encoding="utf-8") as f:
            f.write("\n".join(sorted(words)))
        print(f"ok {fname}: {len(words)} words, {(OUT / fname).stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "eval/data/lex"))
