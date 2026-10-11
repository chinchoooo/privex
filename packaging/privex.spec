# PyInstaller spec for the PRIVEX desktop app (one-folder build).
# Run via packaging/build.py, which builds the UI and fetches models first.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "privex" / "backend"
UI = ROOT / "privex" / "frontend" / "dist"

datas, binaries, hiddenimports = [], [], []
for pkg in ["spacy", "en_core_web_sm", "thinc", "rapidocr_onnxruntime", "onnxruntime",
            "faster_whisper", "ctranslate2", "tokenizers", "imageio_ffmpeg", "av",
            "srsly", "blis", "cymem", "preshed", "murmurhash", "pystray"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += collect_submodules("uvicorn") + collect_submodules("privex_core") + collect_submodules("privex_server")

# Models (face detectors, bundled ASR) — skip the HF download cache folder
for f in (BACKEND / "models").rglob("*"):
    if f.is_file() and ".cache" not in f.parts:
        datas.append((str(f), str(Path("models") / f.relative_to(BACKEND / "models").parent)))
# Name / common-word lexicons used by the NER filter (data files, not picked up by module collection)
for f in (BACKEND / "privex_core" / "text" / "data").glob("*.gz"):
    datas.append((str(f), "privex_core/text/data"))
if not (UI / "index.html").exists():
    sys.exit("UI not built: run `npm run build` in privex/frontend (build.py does this)")
datas.append((str(UI), "ui"))

a = Analysis(
    [str(BACKEND / "launcher.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "paddle", "paddleocr", "tensorflow", "matplotlib", "tkinter", "IPython",
              "pytest", "whisper", "pyarrow", "pandas", "wordfreq", "ftfy"],
    noarchive=False,
)
# PyInstaller picks up an old MSVC runtime (14.36) from the Python install. CTranslate2 (Whisper)
# is built with MSVC >= 17.10 and segfaults in std::mutex against a runtime older than 14.40,
# so ship the build machine's newer redistributable DLLs instead.
_SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
_VCRT = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
if sys.platform == "win32":
    a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _VCRT]
    a.binaries += [(n, str(_SYS32 / n), "BINARY") for n in sorted(_VCRT) if (_SYS32 / n).exists()]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PRIVEX",
    console=False,
    icon=str(Path(SPECPATH) / "privex.ico"),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PRIVEX")
