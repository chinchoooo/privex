# PRIVEX — Local Privacy Firewall

PRIVEX finds and redacts personal data (names, phone numbers, emails, card / bank / ID numbers,
dates of birth, addresses, faces, spoken PII) in **text, images, audio and video** — entirely on
your computer. **No LLM, no cloud calls, no GPU required.**

It ships as:

* **A desktop app** (`PRIVEX.exe`) — a local engine + web UI with human-in-the-loop review for images.
* **A Chrome extension** — warns you *before* you paste personal data into any website (ChatGPT,
  Gmail, forms…) and offers a redacted paste; right-click any image to redact it.

---

## For users

1. Download `PRIVEX-<version>-windows-x64.zip` (or `PRIVEX-<version>-setup.exe`) and run `PRIVEX.exe`.
   A shield icon appears in the system tray and the UI opens at <http://127.0.0.1:8765>.
2. Install the extension: unzip `privex-extension-<version>.zip`, open `chrome://extensions`, enable
   **Developer mode**, click **Load unpacked** and pick the folder.
3. Keep the app running (the installer can start it at sign-in). The extension talks only to
   `127.0.0.1` — your data never leaves the machine.

Everything — OCR, face and speech models — is bundled. No Python, ffmpeg, Ollama or internet needed.

---

## For developers

```bash
cd privex/backend
py -3.12 -m venv .venv                 # Python 3.10–3.12
.venv/Scripts/pip install -r requirements-dev.txt      # (bin/pip on macOS/Linux)
.venv/Scripts/python scripts/fetch_models.py            # YuNet face model + Whisper base.en
.venv/Scripts/python launcher.py                        # → http://127.0.0.1:8765

# UI dev server with hot reload (proxies /api → :8765)
cd ../frontend && npm install && npm run dev            # → http://localhost:5173
```

Behind a corporate proxy / antivirus that intercepts HTTPS, use `pip install --use-feature=truststore …`.

| Task | Command (from `privex/backend`) |
|---|---|
| Tests | `python -m pytest -q` |
| Text benchmarks | `python -m eval.datasets all`, then `python -m eval.run_eval --dataset nemotron\|tab\|synth [--no-ner] [--threshold 0.6]` |
| Generate synthetic set | `python -m eval.synth --n 1000 --seed 1 --out eval/data/synth.jsonl` |
| Build the downloadable app | `python ../../packaging/build.py` (from repo root: `packaging/build.py`) |
| API docs | <http://127.0.0.1:8765/docs> |

---

## How it works

```
                        ┌──────────── privex_core ─────────────┐
 text ────────────────► │ text.analyzer                         │
                        │   recognizers  regex + checksum +     │──► entities (type, span, score, reasons)
 image ─► faces (YuNet) │                context scoring        │
        └► OCR (RapidOCR)│  ner          spaCy en_core_web_sm    │──► boxes ──► review UI ──► apply
           layout → doc ─►│  doc-level    ID-document boost,     │
 audio ─► faster-whisper│               value propagation       │──► word times ──► ffmpeg mute
 video ─► audio + OCR samples + per-frame faces + motion cover ──┼──► streamed H.264 + muted AAC
                        └───────────────────────────────────────┘
 privex_server (FastAPI, 127.0.0.1) ── web UI ── Chrome extension (paste guard, image menu)
```

### Text detection without an LLM

Each recognizer (`privex_core/text/recognizers.py`) produces candidates with a score:

* **Structure + checksums** — Luhn (cards), Verhoeff (Aadhaar), mod-97 (IBAN), SSN area rules, PAN
  holder-type letter, UPI PSP handles, phone digit counts. A checksum pass raises confidence; a fail
  rejects the match or lowers it.
* **Context words** — words near a match raise its score (`DOB`, `card`, `account no`, `OTP`, …) or
  lower it (`tracking number`, `invoice`, `customer care`, …). **The closest context word wins**, and
  on a tie the longer phrase wins, so `DOB 01/02/1990  ISS 03/04/2020` gets the first date as a date
  of birth and the second as an issue date.
* **Document context** — if the text looks like an identity document (`DRIVER LICENSE`, `AADHAAR`,
  `PASSPORT`…), ID-like numbers get a boost and all-caps name lines are proposed.
* **NER** — spaCy's small English model (12 MB) for names and places, run on a same-length
  case-normalised copy so ALL-CAPS OCR text works; name spans are grown over adjacent capitalised words.
* **Resolution** — overlapping candidates: highest score, then longest span. A value confirmed once
  is redacted everywhere it repeats.

Every finding carries human-readable `reasons` (e.g. *"credit_card checksum valid; context 'card'
nearby"*), which the review UI shows in place of the old LLM explanations.

### Images, audio, video

* **Images** — OCR lines are arranged in reading order into one document (so `Name:` and the value on
  the same row are analysed together), then each entity's character span is mapped back to the
  sub-region of its OCR line(s). A same-length cleanup strips glued AAMVA field numbers (`3DOB:` →
  ` DOB:`) without moving offsets. Redaction styles: black, blur, pixelate.
* **Audio** — faster-whisper (int8, CPU) word timestamps → spoken numbers normalised (`nine eight
  seven` → `987`, `double five` → `55`, digit groups joined) → analyzer → mute the matching words.
* **Video** — streaming (constant memory). OCR on sampled frames, skipped on static scenes; values found
  in any sample are boxed in all samples; between samples each box is paired with its nearest
  similar-sized box in the next sample and their bounding rectangle is covered, so moving text stays
  hidden. Faces on every frame, held for one extra frame to avoid flicker.

---

## Benchmarks

All text numbers are **untyped** (a span counts as caught if its characters are hidden, whatever
label PRIVEX gives it) and **scope-aware**: *direct* identifiers must be hidden; *quasi* identifiers
(dates, cities, companies, occupations…) are reported but not penalised. Full outputs are in
`privex/backend/eval/results/`. Reproduce with `python -m eval.datasets all` then the commands below.

| Dataset | Docs | Span recall | Span precision | F1 | Chars leaked | Over-redaction |
|---|---|---|---|---|---|---|
| [Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) held-out half (synthetic, 55 labels, US + intl) | 3,000 | **0.929** | **0.924** | **0.927** | 7.5% | 0.8% |
| same, `--no-ner` (patterns only) | 3,000 | 0.771 | 0.958 | 0.854 | 14.8% | 0.5% |
| [TAB](https://github.com/NorskRegnesentral/text-anonymization-benchmark) test (real ECHR court cases) | 127 | 0.914 | 0.811 | 0.860 | 18.9% | 2.3% |
| Synthetic dev set (`eval/synth.py`) | 500 | 1.000 | 1.000 | 1.000 | 0.0% | 0.6% |

```bash
python -m eval.run_eval --dataset nemotron --split heldout --limit 3000 --seed 11
python -m eval.run_eval --dataset tab
```

**Method.** Nemotron-PII is split 50/50 by a hash of the record id. All rule changes were made by
error analysis on the *dev* half only; the held-out half and TAB were evaluated once at the end
(dev F1 0.920 vs held-out 0.927, so the rules generalise within the dataset). The synthetic set was
used during development and is not an unbiased test. Before this error-analysis round, the same
pipeline scored F1 0.700 (recall 0.661, 51% of characters leaked) on a Nemotron sample.

**Known weak spots** (from the held-out per-label table and TAB misses):
names containing non-ASCII letters (`Stanisław Opałko`, `Osman Özçelik`) are missed by the
pattern recognizers; the name lexicon fires on place/court names (`Northern Ireland`, `High Court`);
ECHR application numbers (`48102/06`); unlabelled single first names in prose; HTTP cookies and
device identifiers written without a label. Labelled-but-unannotated values in Nemotron (e.g.
`Account Number: 987654321`) count as false positives, so precision is somewhat understated.

Throughput (CPU): image ~3 s (OCR dominates); audio ≈ 1× real-time with `base.en`; video ≈ 10× real-time
for moving footage at the default 0.5 s OCR interval, much faster for static footage.

---

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PRIVEX_THRESHOLD` | `0.5` | score at which an entity is redacted |
| `PRIVEX_USE_NER` | `1` | `0` = pattern recognizers only |
| `PRIVEX_SPACY_MODEL` | `en_core_web_sm` | any installed spaCy model (`en_core_web_md/lg/trf`) |
| `PRIVEX_ASR_MODEL` | `base.en` | faster-whisper model name or path (`tiny.en` … `large-v3`) |
| `PRIVEX_OCR_THREADS` | `4` | ONNX Runtime threads (defaults oversubscribe hybrid CPUs, which is ~3× slower) |
| `PRIVEX_FACE_THRESHOLD` | `0.6` | face detector confidence |
| `PRIVEX_VIDEO_OCR_INTERVAL` | `0.5` | seconds between OCR samples |
| `PRIVEX_MAX_VIDEO_SECONDS` | `300` | reject longer videos |
| `PRIVEX_MAX_UPLOAD_MB` | `200` | upload limit |
| `PRIVEX_FILE_TTL_MINUTES` | `60` | uploads/outputs are deleted after this |
| `PRIVEX_PORT` | `8765` | local port (the extension's `apiBase` must match) |
| `PRIVEX_DATA_DIR` | `%LOCALAPPDATA%\Privex` | working files and logs (`privex.log`) |

## Privacy and security

* The server binds to `127.0.0.1` only. CORS admits only browser-extension origins and localhost,
  so a website you visit can't use your PRIVEX engine.
* Uploads and outputs live in `PRIVEX_DATA_DIR/work` and are deleted after the TTL. Review sessions
  expire with them. Download names are random UUIDs.
* Logs record counts and timings, never detected values or transcripts.
* The paste guard **fails open** (pastes the original and shows a notice) when the app isn't running.

## Research directions / known limitations

* **Unicode names** — name patterns use `[A-Za-z]`; switch to Unicode letter classes (top TAB miss).
* **Real evaluation data** — add held-out real-world sets (e.g. annotated forms, ID-card scans,
  call-centre audio) to `eval/` as JSONL; the harness takes `--data`.
* **Names** — the largest error source. Options: larger spaCy models, GLiNER-style span models
  exported to ONNX, gazetteers for Indian names.
* **OCR→pixel mapping** is proportional by character; word-level boxes (RapidOCR `return_word_box`)
  would tighten it. Single-word all-caps names on cards can be missed.
* **Faces** cut off at the frame edge are missed by YuNet; consider tracking or a body/head detector.
* **Video** moving-text coverage assumes roughly linear motion between samples.
* **Audio** — spoken spelled-out emails (`john dot smith at gmail`) are not normalised yet.
* `research/experiments/aes_region_encryption.py` — reversible (keyed) region encryption, an
  alternative to destructive redaction; not yet integrated (note: it derives the IV from the key).

## Repository layout

```
privex/backend/
  privex_core/        detection & redaction engine (no web dependencies)
    text/             recognizers.py · validators.py · ner.py · analyzer.py
    vision/           faces.py · ocr.py · image.py
    audio.py · video.py · media.py · config.py
  privex_server/      FastAPI app + job queue
  launcher.py         desktop entry point (tray icon, opens browser)
  eval/               synthetic data generator + benchmark harness
  tests/              pytest suite
  scripts/            fetch_models.py
  models/             face models (+ asr/ downloaded, git-ignored)
privex/frontend/      React + Vite UI (served by the backend when built)
extension/            Chrome MV3 extension
packaging/            PyInstaller spec, build script, Inno Setup installer
research/             experiments not in the product
```
