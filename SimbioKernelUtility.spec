# PyInstaller spec - used by build_exe.bat (Windows), build_app.sh (macOS/Linux) and the GitHub workflow.   SKU_MODE=onefile (default) | onedir
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ONEDIR = os.environ.get("SKU_MODE", "onefile").lower() == "onedir"
NAME = "SimbioKernelUtility"

sp_datas, sp_bins, sp_hidden = collect_all("spiceypy")  # CSPICE shared library

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=sp_bins,
    datas=[("simbio_utility/resources", "simbio_utility/resources")] + sp_datas,
    hiddenimports=sp_hidden,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "PIL"],
    noarchive=False,
)

# --- Visual C++ runtime fix ---------------------------------------------------------------
# PyInstaller copies vcruntime140*.dll from the *Python* install next to the exe. Python 3.14 ships 14.42,
# but PySide6 >= 6.10 is built against 14.44. The older copy loads first and Qt then fails with
# "ImportError: DLL load failed while importing QtWidgets: The specified procedure could not be found".
# Put the (newer) copies that ship inside the PySide6 wheel at the top level - including msvcp140*.dll, which PyInstaller
# otherwise only places in PySide6\\, leaving Qt to pick up an old msvcp140.dll from System32. run.py also preloads them.
import PySide6

_pyside = Path(PySide6.__file__).parent
_VC = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
       "msvcp140_codecvt_ids.dll", "concrt140.dll")
_newer = {n: _pyside / n for n in _VC if (_pyside / n).exists()}
if _newer:
    a.binaries = [b for b in a.binaries if b[0].lower() not in _newer]  # drop the Python-install copies
    a.binaries = a.binaries + [(n, str(p), "BINARY") for n, p in _newer.items()]  # newer copies at top level

# --- ICU fix ------------------------------------------------------------------------------
# Qt6Core.dll imports the *unversioned* ICU C API (ucnv_open, ...) that Windows 10/11 provides as icuuc.dll in
# System32. PyInstaller's dependency scan may find another ICU on PATH (Anaconda, QGIS, ...) and bundle it; that copy
# exports versioned names (ucnv_open_75), so Qt fails with "DLL load failed ... The specified procedure could not be
# found". Never bundle ICU - let Windows supply it.
import re

_icu = re.compile(r"^icu[a-z]*\d*\.dll$", re.I)
a.binaries = [b for b in a.binaries if not _icu.match(os.path.basename(b[0]))]

pyz = PYZ(a.pure)

# --- per-platform output -----------------------------------------------------------------------
#   Windows : dist/SimbioKernelUtility.exe              (onefile, or onedir with SKU_MODE=onedir)
#   macOS   : dist/SimbioKernelUtility.app              (always onedir inside a .app bundle)
#   Linux   : dist/SimbioKernelUtility                  (onefile, or onedir)
RES = "simbio_utility/resources/"
MAC = sys.platform == "darwin"
icon = RES + "icon.ico" if sys.platform == "win32" else RES + "icon.icns" if MAC else None  # Linux: icon.png is set at run time

if ONEDIR or MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
    if MAC:
        _ver = re.search(r'__version__\s*=\s*"([^"]+)"', Path("simbio_utility/__init__.py").read_text()).group(1)
        app = BUNDLE(coll, name=NAME + ".app", icon=icon, bundle_identifier="it.inaf.simbiokernelutility",
                     info_plist={"CFBundleName": "SIMBIO Kernel Utility", "CFBundleDisplayName": "SIMBIO Kernel Utility",
                                 "CFBundleShortVersionString": _ver, "CFBundleVersion": _ver,
                                 "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=NAME, console=False, icon=icon, upx=False)
