"""Observation geometry of a SIMBIO-SYS camera boresight ("central pixel") at one epoch."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np
import spiceypy as sp
from spiceypy.utils.exceptions import NotFoundError

from . import instruments, seasons, stp as stp_mod, timeconv
from .errors import KernelsNotLoaded, NoIntercept, UtilityError, spice_message

DEFAULT_MU_SUN = 1.32712440018e11  # km^3/s^2, used only if the pool has no BODY10_GM


@dataclass(frozen=True)
class GeometrySettings:
    observer: str = "MPO"
    target: str = "MERCURY"
    method: str = "ELLIPSOID"
    abcorr: str = "LT+S"  # applied to intercept / illumination / sub-point
    lon_domain: str = "180"  # "180" -> -180..180 east,  "360" -> 0..360 east
    seasons: seasons.SeasonConfig = field(default_factory=seasons.SeasonConfig)
    stp: stp_mod.StpTable | None = None  # mission timeline (EVF); None -> MTP/STP not reported


@dataclass
class GeometryResult:
    camera: str
    et: float
    utc: str
    season: str
    season_kind: str
    mta_deg: float
    resolution_m_px: float
    altitude_km: float
    slant_range_km: float
    orbital_velocity_kms: float
    lat_deg: float
    lon_deg: float
    sc_lat_deg: float
    sc_lon_deg: float
    incidence_deg: float
    azimuth_deg: float
    phase_deg: float
    emission_deg: float
    ifov_urad: float
    ifov_source: str
    abcorr: str
    mtp: int | None = None
    stp: int | None = None
    stp_in_mtp: int | None = None
    stp_window: str = ""

    @property
    def plan_label(self) -> str:
        return f"MTP{self.mtp} · STP{self.stp}" if self.mtp is not None else ""

    @property
    def sun_elevation_deg(self) -> float:
        return 90.0 - self.incidence_deg

    @property
    def is_night(self) -> bool:
        return self.incidence_deg >= 90.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sun_elevation_deg"] = self.sun_elevation_deg
        return d


def _wrap_lon(lon_deg: float, domain: str) -> float:
    lon = lon_deg % 360.0
    if domain == "180" and lon > 180.0:
        lon -= 360.0
    return lon


def _radii(target: str) -> np.ndarray:
    try:
        return np.asarray(sp.bodvrd(target, "RADII", 3)[1], dtype=float)
    except Exception as exc:  # no PCK
        raise KernelsNotLoaded(f"No RADII for {target} in the kernel pool (PCK missing?).") from exc


def mercury_true_anomaly(et: float) -> tuple[float, float]:
    """(true anomaly deg in [0,360), eccentricity) of Mercury's heliocentric orbit at ``et``."""
    state, _lt = sp.spkezr("MERCURY", et, "ECLIPJ2000", "NONE", "SUN")
    try:
        mu = float(sp.bodvrd("SUN", "GM", 1)[1][0])
    except Exception:
        mu = DEFAULT_MU_SUN
    elts = sp.oscltx(state, et, mu)
    return math.degrees(elts[8]) % 360.0, float(elts[1])


def sun_azimuth_deg(spoint: np.ndarray, sun_vec: np.ndarray, radii: np.ndarray) -> float:
    """Azimuth of the Sun at ``spoint`` (body-fixed), measured clockwise from local north, 0..360."""
    normal = np.asarray(sp.surfnm(*radii, spoint))
    east = np.cross([0.0, 0.0, 1.0], normal)
    norm = np.linalg.norm(east)
    if norm < 1e-12:  # exactly at a pole: azimuth undefined, use the prime meridian as reference
        east = np.cross([0.0, 1.0, 0.0], normal)
        norm = np.linalg.norm(east)
    east /= norm
    north = np.cross(normal, east)
    return math.degrees(math.atan2(np.dot(sun_vec, east), np.dot(sun_vec, north))) % 360.0


def compute(camera: str, et: float, settings: GeometrySettings = GeometrySettings()) -> GeometryResult:
    s = settings
    fixref = f"IAU_{s.target}"
    try:
        cam_id = sp.bodn2c(camera)
    except Exception as exc:
        raise UtilityError(f"Unknown instrument '{camera}' (is the IK/FK loaded?).") from exc

    _shape, frame, bsight, _n, _bounds = sp.getfov(cam_id, 100)

    try:
        spoint, trgepc, srfvec = sp.sincpt(s.method, s.target, et, fixref, s.abcorr, s.observer, frame, bsight)
    except NotFoundError as exc:
        raise NoIntercept(f"The {camera} boresight does not intersect {s.target} at this time.") from exc
    except Exception as exc:
        raise UtilityError("SPICE error: " + spice_message(exc)) from exc

    try:
        trgepc, _srf, phase, incdnc, emissn, _vis, _lit = sp.illumf(
            s.method, s.target, "SUN", et, fixref, s.abcorr, s.observer, spoint)
        radii = _radii(s.target)
        sun_pos, _lt = sp.spkpos("SUN", trgepc, fixref, s.abcorr, s.target)
        azimuth = sun_azimuth_deg(np.asarray(spoint), np.asarray(sun_pos) - np.asarray(spoint), radii)

        # central pixel coordinates (planetocentric, east-positive) -- same convention as timefinder.py
        _r, lon, lat = sp.reclat(spoint)

        # sub-spacecraft point and altitude above the reference ellipsoid
        sub, _t, subvec = sp.subpnt(f"NEAR POINT/{s.method}", s.target, et, fixref, s.abcorr, s.observer)
        _r2, sublon, sublat = sp.reclat(sub)
        altitude = sp.vnorm(subvec)

        slant_km = sp.vnorm(srfvec)

        state, _lt = sp.spkezr(s.observer, et, "J2000", "NONE", s.target)
        velocity = sp.vnorm(state[3:])

        mta, ecc = mercury_true_anomaly(et)
        epoch_et = timeconv.utc_to_et(s.seasons.epoch_utc)
        season = seasons.classify(mta, ecc, et, epoch_et, s.seasons)
    except UtilityError:
        raise
    except Exception as exc:
        raise UtilityError("SPICE error: " + spice_message(exc)) from exc

    optics = instruments.optics_for(camera) or instruments.optics_from_fov(cam_id)
    if optics is None:
        raise UtilityError(f"No optical parameters known for {camera}; add them in core/instruments.py.")
    cos_em = math.cos(emissn)
    resolution = slant_km * 1e3 * optics.ifov_rad / cos_em if cos_em > 1e-6 else float("inf")

    utc = timeconv.et_to_utc(et, 3)
    plan = _plan_for(utc, s.stp)
    return GeometryResult(
        camera=camera,
        et=et,
        utc=utc,
        season=season.label,
        season_kind=season.kind,
        mta_deg=mta,
        resolution_m_px=resolution,
        altitude_km=altitude,
        slant_range_km=slant_km,
        orbital_velocity_kms=velocity,
        lat_deg=math.degrees(lat),
        lon_deg=_wrap_lon(math.degrees(lon), s.lon_domain),
        sc_lat_deg=math.degrees(sublat),
        sc_lon_deg=_wrap_lon(math.degrees(sublon), s.lon_domain),
        incidence_deg=math.degrees(incdnc),
        azimuth_deg=azimuth,
        phase_deg=math.degrees(phase),
        emission_deg=math.degrees(emissn),
        ifov_urad=optics.ifov_rad * 1e6,
        ifov_source=optics.source,
        abcorr=s.abcorr,
        mtp=plan.mtp if plan else None,
        stp=plan.stp if plan else None,
        stp_in_mtp=plan.stp_in_mtp if plan else None,
        stp_window=plan.window if plan else "",
    )


def _plan_for(utc: str, table: stp_mod.StpTable | None):
    if table is None:
        return None
    try:
        return table.lookup(datetime.strptime(utc, "%Y-%m-%dT%H:%M:%S.%f"))
    except ValueError:  # e.g. a leap second 23:59:60
        return None
