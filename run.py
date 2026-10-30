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
    try:
        text += "\nLoaded modules:\n  " + "\n  ".join(_loaded_modules())
    except Exception as exc:
        text += f"\n(could not list modules: {exc})"
    text += f"\n\nPython {sys.version}\nframe={getattr(sys, 'frozen', False)}  exe={sys.executable}\n"
    log = Path(os.environ.get("TEMP", ".")) / "SimbioKernelUtility_startup.log"
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


if __name__ == "__main__":
    try:
        _preload_vc_runtime()
        from simbio_utility.gui.app import main
        code = main()
    except Exception:
        _report_startup_failure()
        code = 1
    sys.exit(code)
