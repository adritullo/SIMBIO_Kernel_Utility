import sys
from pathlib import Path


def resource_path(name: str) -> Path:
    """Resolve a bundled resource both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    p = base / "resources" / name
    return p if p.exists() else Path(__file__).parent / "resources" / name


EXAMPLE_DTM = "exampleDTM.tif"
