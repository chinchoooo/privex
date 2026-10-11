"""
Build the downloadable PRIVEX bundle.

    privex/backend/.venv/Scripts/python packaging/build.py            # full build
    privex/backend/.venv/Scripts/python packaging/build.py --skip-ui  # reuse frontend/dist

Produces in dist/:
    PRIVEX/                         the app folder (run PRIVEX.exe)
    PRIVEX-<ver>-windows-x64.zip    the app, zipped for download
    privex-extension-<ver>.zip      the Chrome extension (load unpacked, or upload to the Web Store)
    PRIVEX-<ver>-setup.exe          installer, if Inno Setup (iscc) is installed
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "privex" / "backend"
FRONTEND = ROOT / "privex" / "frontend"
EXTENSION = ROOT / "extension"
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"


def run(cmd: list[str], cwd: Path | None = None):
    print("»", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == "win32" and cmd[0] == "npm"))


def version() -> str:
    sys.path.insert(0, str(BACKEND))
    from privex_core import __version__
    return __version__


def make_icon():
    ico = PACKAGING / "privex.ico"
    if ico.exists():
        return
    from PIL import Image
    Image.open(EXTENSION / "icons" / "icon128.png").save(ico, sizes=[(16, 16), (32, 32), (48, 48), (128, 128)])


def zip_dir(src: Path, dest: Path, arc_root: str):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, Path(arc_root) / f.relative_to(src))
    print(f"ok {dest.relative_to(ROOT)}  ({dest.stat().st_size / 1e6:.0f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ui", action="store_true")
    ap.add_argument("--skip-models", action="store_true", help="don't bundle the ASR model (downloaded on first use)")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    ver = version()
    DIST.mkdir(exist_ok=True)

    if not a.skip_ui:
        run(["npm", "install", "--no-audit", "--no-fund"], FRONTEND)
        run(["npm", "run", "build"], FRONTEND)

    run([sys.executable, str(BACKEND / "scripts" / "fetch_models.py")] + (["--skip-asr"] if a.skip_models else []))
    make_icon()

    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "privex.spec"), "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build")])

    # Extension: keep manifest version in sync with the app
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != ver:
        manifest["version"] = ver
        (EXTENSION / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    zip_dir(EXTENSION, DIST / f"privex-extension-{ver}.zip", ".")

    if not a.no_zip:
        zip_dir(DIST / "PRIVEX", DIST / f"PRIVEX-{ver}-windows-x64.zip", "PRIVEX")

    iscc = shutil.which("iscc") or next((p for p in [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"), Path(r"C:\Program Files\Inno Setup 6\ISCC.exe")]
        if p.exists()), None)
    if iscc:
        run([str(iscc), f"/DAppVersion={ver}", f"/O{DIST}", str(PACKAGING / "installer.iss")])
    else:
        print("note: Inno Setup not found — skipping installer (the zip is the download).")


if __name__ == "__main__":
    main()
