"""Build the backend as one executable and drop it where Tauri bundles sidecars (PLAN Phase 6).

    cd backend && uv run python scripts/build_sidecar.py

Output: apps/desktop/src-tauri/binaries/ziko-backend-<rust target triple>[.exe], the name Tauri's
`externalBin: ["binaries/ziko-backend"]` expects. Run it on each OS you ship: PyInstaller can't
cross-compile.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import PyInstaller.__main__

BACKEND = Path(__file__).resolve().parents[1]
BINARIES = BACKEND.parent / "apps" / "desktop" / "src-tauri" / "binaries"


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("host: "))


def main() -> None:
    os.chdir(BACKEND)
    sep = os.pathsep
    work = Path(tempfile.mkdtemp(prefix="ziko-pyi-"))
    args = [
        "ziko_backend.py",
        "--name=ziko-backend",
        "--onefile",
        "--noconfirm",
        "--clean",
        "--console",  # Tauri reads stdout/stderr; Windows builds hide the console via the parent process
        f"--distpath={BACKEND / 'dist'}",
        f"--workpath={work}",
        f"--specpath={work}",
        # migrate.py resolves these next to the bundle root (Path(__file__).parents[2] == _MEIPASS)
        f"--add-data={BACKEND / 'alembic.ini'}{sep}.",
        f"--add-data={BACKEND / 'alembic'}{sep}alembic",
        f"--add-data={BACKEND / 'app' / 'assets'}{sep}app/assets",
        # dynamically imported or data-bearing packages
        "--collect-all=livekit.wakeword",  # feature-extraction ONNX models live in package resources
        "--collect-all=google.genai",
        "--collect-binaries=onnxruntime",
        "--collect-submodules=uvicorn",
        "--collect-submodules=keyring",
        "--collect-submodules=app",
        "--collect-data=certifi",
        "--exclude-module=pvporcupine",  # optional engine, not wired in this build
        "--exclude-module=torch",
        "--exclude-module=tkinter",
    ]
    if sys.platform == "win32" or sys.platform == "darwin":
        args.append("--collect-all=_sounddevice_data")  # PortAudio ships inside the wheel there
    PyInstaller.__main__.run(args)
    shutil.rmtree(work, ignore_errors=True)

    exe = BACKEND / "dist" / ("ziko-backend.exe" if sys.platform == "win32" else "ziko-backend")
    BINARIES.mkdir(parents=True, exist_ok=True)
    dest = BINARIES / f"ziko-backend-{target_triple()}{exe.suffix}"
    shutil.copy2(exe, dest)
    print(f"sidecar -> {dest} ({dest.stat().st_size / 1e6:.0f} MB)")  # ASCII: Windows consoles are cp1252


if __name__ == "__main__":
    main()
