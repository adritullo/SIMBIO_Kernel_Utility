"""Run the *built* app's self-test (see run.py --selftest).  Usage: python scripts/smoke_test.py   (after pyinstaller)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
dist = root / "dist"
if sys.platform == "win32":
    exe = dist / "SimbioKernelUtility.exe"
    if not exe.exists():
        exe = dist / "SimbioKernelUtility" / "SimbioKernelUtility.exe"
elif sys.platform == "darwin":
    exe = dist / "SimbioKernelUtility.app" / "Contents" / "MacOS" / "SimbioKernelUtility"
else:
    exe = dist / "SimbioKernelUtility"
    if not exe.is_file():
        exe = dist / "SimbioKernelUtility" / "SimbioKernelUtility"
if not exe.exists():
    sys.exit(f"built app not found: {exe}")

out = Path(tempfile.mkdtemp()) / "selftest.txt"
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
try:
    r = subprocess.run([str(exe), "--selftest", str(out)], env=env, timeout=180)
except subprocess.TimeoutExpired:
    sys.exit("self-test timed out")
text = out.read_text(encoding="utf-8") if out.exists() else "(no result file written - the app crashed before the self-test)"
print(text)
sys.exit(0 if r.returncode == 0 and "SELFTEST OK" in text else 1)
