import sys
from pathlib import Path


def resource_path(name: str) -> Path:
    """Resolve a bundled resource both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    p = base / "resources" / name
    return p if p.exists() else Path(__file__).parent / "resources" / name


def example_mk_path() -> str:
    """Placeholder path in the OS' own style."""
    if sys.platform == "win32":
        return r"F:\BEPICOLOMBO_ops\data\SPICE\BEPICOLOMBO\kernels\mk\bc_nadir_plan_ES.tm"
    return "~/BEPICOLOMBO_ops/data/SPICE/BEPICOLOMBO/kernels/mk/bc_nadir_plan_ES.tm"


def example_out_dir() -> str:
    return r"F:\BEPICOLOMBO_ops" if sys.platform == "win32" else "~/BEPICOLOMBO_ops"


EXAMPLE_DTMS = {"STC": "exampleDTM_STC.tif", "HRIC": "exampleDTM_HRIC.tif"}


def dtm_family(channel: str) -> str:
    """Reference-DTM family of a channel: HRIC has its own terrain, STC (-H/-L) and VIHI share the other."""
    return "HRIC" if channel.upper().startswith("HRIC") else "STC"


def default_dtm(channel: str) -> Path:
    return resource_path(EXAMPLE_DTMS[dtm_family(channel)])
