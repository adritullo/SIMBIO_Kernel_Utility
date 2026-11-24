"""Positional search: when does a camera see a given surface point (lat/lon) in a time range?

Two-level scan, pure SPICE (no Qt) so it can be unit-tested and run in small slices from the GUI:

1. **Coarse** (``COARSE_STEP`` = 60 s, longer jumps when the point is far below the horizon): the spacecraft position
   in the Mercury-fixed frame tells whether the point can be above the spacecraft's horizon at all.  When it can,
   the angle between the point and the camera boresight is computed with the real attitude (``pxform``).
2. **Adaptive**: the next epoch is as far ahead as the point provably cannot reach the FOV (distance to the FOV edge
   divided by an upper bound of its angular rate, incl. slews of up to 0.5 deg/s), between the fine step (about a
   quarter of the narrowest FOV crossing time, 0.1-10 s) and ``COARSE_STEP``; inside the FOV the fine step is used and
   every epoch is tested with ``fovray``.  This catches short crossings (HRIC, the narrow STC strips) that a plain
   minute grid would miss.

Consecutive in-FOV samples form a *pass*; for each pass the sample with the best (smallest) ground resolution is
reported with its geometry.  Times are second-accurate at the fine step; ranges with no ephemeris or no attitude are
skipped and counted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterator

import numpy as np
import spiceypy as sp

from . import instruments
from .errors import UtilityError
from .timeconv import et_to_utc

COARSE_STEP = 60.0  # s
NO_DATA_SKIP = 600.0  # s, jump after an epoch without ephemeris / attitude
HORIZON_MARGIN = math.radians(2.0)
ATTITUDE_RATE = math.radians(0.5)  # rad/s of slew allowed for when deciding whether a minute must be refined


@dataclass
class Sample:
    et: float
    resolution_m_px: float
    emission_deg: float
    incidence_deg: float
    phase_deg: float
    slant_km: float


@dataclass
class Pass:
    start_et: float
    end_et: float
    best: Sample
    samples: int = 1

    @property
    def duration_s(self) -> float:
        return self.end_et - self.start_et

    @property
    def lit(self) -> bool:
        return self.best.incidence_deg < 90.0

    def row(self) -> dict:
        b = self.best
        return {
            "start_utc": et_to_utc(self.start_et, 0), "end_utc": et_to_utc(self.end_et, 0),
            "duration_s": round(self.duration_s, 1), "best_utc": et_to_utc(b.et, 0), "best_et": b.et,
            "resolution_m_px": b.resolution_m_px, "emission_deg": b.emission_deg, "incidence_deg": b.incidence_deg,
            "phase_deg": b.phase_deg, "slant_range_km": b.slant_km, "lit": self.lit,
        }


@dataclass
class SearchResult:
    passes: list[Pass] = field(default_factory=list)
    no_ephemeris_s: float = 0.0
    no_attitude_s: float = 0.0
    dark_passes: int = 0  # passes dropped because the point was not sunlit (when sunlit_only)
    cancelled: bool = False

    def summary(self) -> str:
        s = f"{len(self.passes)} pass{'es' if len(self.passes) != 1 else ''}"
        if self.dark_passes:
            s += f" ({self.dark_passes} more on the night side, hidden)"
        gaps = []
        if self.no_ephemeris_s > 0:
            gaps.append(f"{self.no_ephemeris_s / 86400:.1f} d without spacecraft ephemeris")
        if self.no_attitude_s > 0:
            gaps.append(f"{self.no_attitude_s / 86400:.1f} d without attitude (CK)")
        if gaps:
            s += " · skipped " + ", ".join(gaps)
        if self.cancelled:
            s += " · cancelled"
        return s


def surface_point(lat_deg: float, lon_deg: float, radii: np.ndarray) -> np.ndarray:
    """Planetocentric lat/lon (east-positive) -> point on the reference ellipsoid, body-fixed km."""
    u = np.asarray(sp.latrec(1.0, math.radians(lon_deg), math.radians(lat_deg)))
    a, b, c = radii
    return u / math.sqrt((u[0] / a) ** 2 + (u[1] / b) ** 2 + (u[2] / c) ** 2)


def _vsep(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return math.acos(max(-1.0, min(1.0, float(np.dot(a, b) / (na * nb)))))


class PositionSearch:
    """Cooperative search: call :meth:`steps` and consume it in slices (the GUI does a few hundred per timer tick)."""

    def __init__(self, camera: str, lat_deg: float, lon_deg: float, et0: float, et1: float, *, observer: str = "MPO",
                 target: str = "MERCURY", sunlit_only: bool = True, coarse_step: float = COARSE_STEP) -> None:
        if not et1 > et0:
            raise UtilityError("The end of the range must be after its start.")
        if not -90.0 <= lat_deg <= 90.0:
            raise UtilityError("Latitude must be between -90 and 90 degrees.")
        self.camera, self.observer, self.target = camera, observer, target
        self.lat, self.lon = lat_deg, lon_deg
        self.et0, self.et1, self.step = et0, et1, coarse_step
        self.sunlit_only = sunlit_only
        self.fixref = f"IAU_{target}"
        try:
            self.cam_id = sp.bodn2c(camera)
            _shape, self.cam_frame, bsight, _n, bounds = sp.getfov(self.cam_id, 100)
        except Exception as exc:
            raise UtilityError(f"Unknown instrument '{camera}' (is the IK/FK loaded?).") from exc
        try:
            self.radii = np.asarray(sp.bodvrd(target, "RADII", 3)[1], dtype=float)
        except Exception as exc:
            raise UtilityError(f"No RADII for {target} in the kernel pool (PCK missing?).") from exc
        self.bsight = np.asarray(bsight, dtype=float)
        seps = [_vsep(self.bsight, np.asarray(b)) for b in bounds]
        self.fov_half = max(seps)  # boresight -> farthest corner
        # narrowest full width: corners of a rectangle -> half of the shortest corner-to-corner edge, crude but safe
        edges = [_vsep(np.asarray(bounds[i]), np.asarray(bounds[(i + 1) % len(bounds)])) for i in range(len(bounds))]
        self.fov_narrow = max(min(edges), math.radians(0.01)) if len(bounds) > 1 else 2 * self.fov_half
        self.point = surface_point(lat_deg, lon_deg, self.radii)
        self.normal = np.asarray(sp.surfnm(*self.radii, self.point))
        self.r_mean = float(np.mean(self.radii))
        optics = instruments.optics_for(camera) or instruments.optics_from_fov(self.cam_id)
        self.ifov = optics.ifov_rad if optics else float("nan")
        self.result = SearchResult()
        self.progress = 0.0  # 0..1
        self._inside: list[Sample] = []  # samples of the pass being built
        self._last_inside_et: float | None = None
        self._fine_step = COARSE_STEP

    # -------------------------------------------------------------------- geometry at one epoch
    def _sc_state(self, et: float) -> np.ndarray:
        st, _lt = sp.spkezr(self.observer, et, self.fixref, "NONE", self.target)
        return np.asarray(st)

    def _los_cam(self, et: float, sc: np.ndarray) -> np.ndarray:
        m = np.asarray(sp.pxform(self.fixref, self.cam_frame, et))
        return m @ (self.point - sc)

    def _sample(self, et: float, sc: np.ndarray) -> Sample:
        v = sc - self.point
        slant = float(np.linalg.norm(v))
        emission = _vsep(self.normal, v)
        sun, _lt = sp.spkpos("SUN", et, self.fixref, "NONE", self.target)
        to_sun = np.asarray(sun) - self.point
        incidence = _vsep(self.normal, to_sun)
        phase = _vsep(to_sun, v)
        ce = math.cos(emission)
        res = slant * 1e3 * self.ifov / ce if ce > 1e-6 else float("inf")
        return Sample(et, res, math.degrees(emission), math.degrees(incidence), math.degrees(phase), slant)

    def _in_fov(self, et: float) -> Sample | None:
        sc = self._sc_state(et)[:3]
        if np.dot(sc - self.point, self.normal) <= 0:  # point below the local horizon of the spacecraft
            return None
        los = self._los_cam(et, sc)
        if not sp.fovray(self.camera, los, self.cam_frame, "NONE", self.observer, et):
            return None
        return self._sample(et, sc)

    # -------------------------------------------------------------------- pass bookkeeping
    def _add_inside(self, s: Sample) -> None:
        self._inside.append(s)
        self._last_inside_et = s.et

    def _close_pass(self) -> None:
        if not self._inside:
            return
        best = min(self._inside, key=lambda s: s.resolution_m_px)
        p = Pass(self._inside[0].et, self._inside[-1].et, best, len(self._inside))
        if self.sunlit_only and not p.lit:
            self.result.dark_passes += 1
        else:
            self.result.passes.append(p)
        self._inside = []
        self._last_inside_et = None

    # -------------------------------------------------------------------- main loop
    def steps(self, cancel: Callable[[], bool] = lambda: False) -> Iterator[float]:
        """Generator: one epoch per iteration, yielding the progress (0..1).

        Adaptive stepping: the next epoch is as far as the point provably cannot reach the FOV (angular distance to the
        FOV edge divided by an upper bound of its angular rate in the camera frame), at most ``coarse_step``, at least
        the fine step; far below the horizon the jump is bounded by the orbital rate instead."""
        et = self.et0
        span = self.et1 - self.et0
        while et <= self.et1:
            if cancel():
                self.result.cancelled = True
                break
            self.progress = (et - self.et0) / span
            yield self.progress
            try:
                st = self._sc_state(et)
            except Exception:
                self.result.no_ephemeris_s += NO_DATA_SKIP
                self._close_pass()
                et += NO_DATA_SKIP
                continue
            sc, vel = st[:3], st[3:]
            r = float(np.linalg.norm(sc))
            omega = float(np.linalg.norm(np.cross(sc, vel))) / (r * r) + 2e-6  # sub-S/C angular rate + Mercury rotation
            theta = _vsep(sc, self.point)  # central angle sub-spacecraft point -> target point
            horizon = math.acos(min(1.0, self.r_mean / r))
            if theta > horizon + HORIZON_MARGIN or np.dot(sc - self.point, self.normal) <= 0:
                self._close_pass()
                et += min(max(self.step if theta > horizon + HORIZON_MARGIN else 1.0,
                              0.8 * (theta - horizon) / omega), 6 * 3600.0)
                continue
            try:
                los = self._los_cam(et, sc)
            except Exception:
                self.result.no_attitude_s += NO_DATA_SKIP
                self._close_pass()
                et += NO_DATA_SKIP
                continue
            dist = float(np.linalg.norm(los))
            trans = float(np.linalg.norm(vel)) / max(dist, 1.0)  # rad/s, ground motion seen from the camera
            rate = 1.5 * trans + ATTITUDE_RATE
            fine = min(10.0, max(0.1, self.fov_narrow / (trans + omega) / 4.0))
            self._fine_step = fine
            sep = _vsep(self.bsight, los)
            if sep <= self.fov_half and sp.fovray(self.camera, los, self.cam_frame, "NONE", self.observer, et):
                self._add_inside(self._sample(et, sc))
                et += fine
                continue
            self._close_pass()
            et += min(self.step, max(fine, 0.8 * (sep - self.fov_half) / rate))
        self._close_pass()
        self.progress = 1.0
        yield 1.0

    def run(self, cancel: Callable[[], bool] = lambda: False) -> SearchResult:
        for _ in self.steps(cancel):
            pass
        return self.result
