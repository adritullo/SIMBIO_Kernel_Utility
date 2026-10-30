"""Entry point.  Also hardens start-up on Windows (see _preload_vc_runtime) and logs start-up failures."""
import os
import sys
import traceback
from pathlib import Path

_VC_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
            "msvcp140_codecvt_ids.dll", "concrt140.dll")


def _pyside_dirs() -> list[Path]:
    dirs = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs += [Path(base) / "PySide6", Path(base) / "shiboken6", Path(base)]
    try:
        import importlib.util
        spec = importlib.util.find_spec("PySide6")
        if spec and spec.submodule_search_locations:
            dirs.append(Path(list(spec.submodule_search_locations)[0]))
    except Exception:
        pass
    return [d for d in dirs if d.is_dir()]


def _preload_vc_runtime() -> None:
    """Load the Visual C++ runtime that ships with PySide6 *by full path* before Qt is imported.

    Windows resolves a dependency named 'msvcp140.dll' to a module that is already loaded under that name, so
    the (new) bundled copy wins over an older one in System32 - the cause of
    'ImportError: DLL load failed while importing QtWidgets: The specified procedure could not be found'.
    """
    if sys.platform != "win32":
        return
    import ctypes
    for d in _pyside_dirs():
        try:
            os.add_dll_directory(str(d))
        except Exception:
            pass
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    done = set()
    for d in _pyside_dirs():
        for name in _VC_DLLS:
            p = d / name
            if name not in done and p.is_file():
                try:
                    ctypes.WinDLL(str(p))
                    done.add(name)
                except OSError:
                    pass


def _loaded_modules() -> list[str]:
    """Paths of the VC/Qt DLLs currently loaded in this process (diagnostics)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    k32, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    proc = k32.GetCurrentProcess()
    mods = (wintypes.HMODULE * 2048)()
    need = wintypes.DWORD()
    psapi.EnumProcessModules(proc, mods, ctypes.sizeof(mods), ctypes.byref(need))
    out = []
    for m in mods[: need.value // ctypes.sizeof(wintypes.HMODULE)]:
        buf = ctypes.create_unicode_buffer(520)
        psapi.GetModuleFileNameExW(proc, m, buf, 520)
        if any(k in buf.value.lower() for k in ("msvcp", "vcruntime", "concrt", "qt6", "python3", "shiboken", "pyside", "icu")):
            out.append(buf.value)
    return sorted(out)


def _report_startup_failure() -> None:
    text = traceback.format_exc()
    if sys.platform == "win32":
        try:
            text += "\nLoaded modules:\n  " + "\n  ".join(_loaded_modules())
        except Exception as exc:
            text += f"\n(could not list modules: {exc})"
    text += f"\n\nPython {sys.version}\nframe={getattr(sys, 'frozen', False)}  exe={sys.executable}\n"
    import tempfile
    log = Path(tempfile.gettempdir()) / "SimbioKernelUtility_startup.log"
    try:
        log.write_text(text, encoding="utf-8")
    except Exception:
        pass
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, f"The application could not start.\n\nDetails were written to:\n{log}\n\n{text.splitlines()[-1] if text else ''}"[:1500],
            "SIMBIO Kernel Utility", 0x10)
    else:
        print(text, file=sys.stderr)


def _selftest(outfile: str) -> int:
    """`SimbioKernelUtility --selftest result.txt` - used by the build scripts / CI to prove the *built* app is healthy:
    Qt widgets import and a window builds, the CSPICE library loads, and every bundled resource is present and readable."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []
    try:
        import spiceypy as sp
        lines.append(f"CSPICE {sp.tkvrsn('TOOLKIT')}")
        from PySide6.QtWidgets import QApplication
        from simbio_utility import __version__
        from simbio_utility.config import AppConfig
        from simbio_utility.core import dtm
        from simbio_utility.gui.main_window import MainWindow
        from simbio_utility.gui.theme import apply_theme
        from simbio_utility.resources import default_dtm, resource_path
        app = QApplication([])
        apply_theme(app)
        win = MainWindow()
        win.show()
        app.processEvents()
        lines.append(f"window ok: {win.windowTitle()} v{__version__}, {len(win.cards)} cards")
        win.close()
        for n in ("icon.png", "icon.ico", "stp_default.evf", "arrow-down.png", "check.png"):
            assert resource_path(n).is_file(), f"missing resource {n}"
        for ch in ("STC-H", "HRIC"):
            d = dtm.load_dtm(default_dtm(ch), max_dim=200)
            lines.append(f"DTM {ch}: {d.z.shape} @ {d.pixel_size_m:g} m/px")
        lines.append(f"EVF: {AppConfig().stp_table().summary()}")
        lines.append("SELFTEST OK")
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("SELFTEST FAILED")
        code = 1
    Path(outfile).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        _preload_vc_runtime()
        if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
            sys.exit(_selftest(sys.argv[2]))
        from simbio_utility.gui.app import main
        code = main()
    except Exception:
        _report_startup_failure()
        code = 1
    sys.exit(code)
