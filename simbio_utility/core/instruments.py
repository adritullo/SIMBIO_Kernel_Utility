"""Camera catalogue: discovery from the kernel pool + optical parameters for resolution."""
from __future__ import annotations

import re
from dataclasses import dataclass

import spiceypy as sp

PREFIX = "MPO_SIMBIO-SYS_"

# Fallback list shown when nothing can be discovered from the pool (names as used in the ESA IK).
FALLBACK_CAMERAS = (
    "MPO_SIMBIO-SYS_STC-H_P700",
    "MPO_SIMBIO-SYS_STC-L_P700",
    "MPO_SIMBIO-SYS_STC-H_F420",
    "MPO_SIMBIO-SYS_STC-H_F550",
    "MPO_SIMBIO-SYS_STC-L_F550",
    "MPO_SIMBIO-SYS_STC-H_F750",
    "MPO_SIMBIO-SYS_STC-L_F920",
    "MPO_SIMBIO-SYS_HRIC_FPAN",
    "MPO_SIMBIO-SYS_VIHI_FPA",
)


@dataclass(frozen=True)
class Optics:
    pixel_pitch_m: float
    focal_length_m: float
    source: str

    @property
    def ifov_rad(self) -> float:
        return self.pixel_pitch_m / self.focal_length_m


# Same values as the original timefinder.py (STC 95 mm / 10 um, HRIC 800 mm / 10 um, VIHI 160 mm / 40 um).
_OPTICS_BY_CHANNEL = {
    "STC": Optics(10e-6, 0.095, "table (STC: 95 mm, 10 um)"),
    "HRIC": Optics(10e-6, 0.800, "table (HRIC: 800 mm, 10 um)"),
    "VIHI": Optics(40e-6, 0.160, "table (VIHI: 160 mm, 40 um)"),
}


@dataclass(frozen=True)
class Camera:
    name: str
    channel: str  # e.g. STC-H, STC-L, HRIC, VIHI
    filter: str  # e.g. P700, F420, FPAN
    available: bool  # present in the loaded kernel pool

    @property
    def label(self) -> str:
        return f"{self.channel} / {self.filter}"


def split_name(name: str) -> tuple[str, str]:
    short = name[len(PREFIX):] if name.startswith(PREFIX) else name
    channel, _, flt = short.rpartition("_")
    return (channel or short), flt


def optics_for(name: str) -> Optics | None:
    channel, _ = split_name(name)
    for key, optics in _OPTICS_BY_CHANNEL.items():
        if channel.upper().startswith(key):
            return optics
    return None


def optics_from_fov(camera_id: int) -> Optics | None:
    """Fallback: derive the IFOV from the IK FOV and pixel counts (unit focal length trick)."""
    try:
        _shape, _frame, bsight, _n, bounds = sp.getfov(camera_id, 100)
        samples = int(sp.gdpool(f"INS{camera_id}_PIXEL_SAMPLES", 0, 1)[0])
    except Exception:
        return None
    width = sp.vsep(bounds[0], bounds[1])  # angular size along one detector side
    if width <= 0 or samples <= 0:
        return None
    ifov = width / samples
    return Optics(ifov, 1.0, "derived from IK field of view")


def _pool_camera_names() -> list[str]:
    names: list[str] = []
    try:
        pool = sp.gnpool("INS*_PIXEL_SAMPLES", 0, 1000)
    except Exception:
        return names
    for var in pool:
        m = re.fullmatch(r"INS(-?\d+)_PIXEL_SAMPLES", var)
        if not m:
            continue
        try:
            name = sp.bodc2n(int(m.group(1)))
        except Exception:
            continue
        if name:
            names.append(name)
    return names


def is_whole_stc(channel: str) -> bool:
    """Any STC entry other than the STC-H / STC-L channels (i.e. the whole focal plane, 'STC', 'STC-FPA'...):
    not used for science, so it is not offered."""
    c = channel.strip().upper()
    return c.startswith("STC") and c not in ("STC-H", "STC-L")


def discover_cameras() -> list[Camera]:
    """SIMBIO-SYS cameras found in the pool, falling back to the known list (marked unavailable).

    The generic whole-focal-plane 'STC' camera is left out: only the STC-H and STC-L channels are listed."""
    found = sorted({n for n in _pool_camera_names() if n.startswith(PREFIX)})
    if not found:
        found = sorted({n for n in _pool_camera_names()})
    cams = [Camera(n, *split_name(n), available=True) for n in found]
    cams = [c for c in cams if not is_whole_stc(c.channel)]
    if not cams:
        cams = [Camera(n, *split_name(n), available=False) for n in FALLBACK_CAMERAS]
    return sorted(cams, key=lambda c: (c.channel, c.filter))
