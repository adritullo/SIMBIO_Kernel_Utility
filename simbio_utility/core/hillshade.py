"""Hillshade of a reference DTM for a given solar azimuth / incidence angle.

Conventions (same as SPICE geometry output of this app):
  * azimuth  - direction *towards the Sun*, degrees clockwise from north
  * incidence - angle between the Sun direction and the local vertical (0 = Sun at zenith)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AMBIENT = 0.03


@dataclass
class Hillshade:
    image: np.ndarray  # uint8, (H, W)
    flat_level: float  # cos(incidence): brightness a perfectly flat surface would get (0..1)
    shadow_fraction: float  # fraction of pixels in cast shadow (0 if cast shadows disabled)
    azimuth_deg: float
    incidence_deg: float
    night: bool
    stretched: bool


def _shifted(z: np.ndarray, dr: int, dc: int) -> np.ndarray:
    """out[r, c] = z[r + dr, c + dc]; -inf outside the grid (nothing occludes beyond the DTM edge)."""
    h, w = z.shape
    out = np.full_like(z, -np.inf)
    r0, r1 = max(0, -dr), min(h, h - dr)
    c0, c1 = max(0, -dc), min(w, w - dc)
    if r1 > r0 and c1 > c0:
        out[r0:r1, c0:c1] = z[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
    return out


def cast_shadow_mask(z: np.ndarray, pixel_size_m: float, azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Approximate terrain self-shadowing by sampling the horizon towards the Sun at growing distances."""
    if elevation_deg <= 0.0:
        return np.ones(z.shape, dtype=bool)
    az = np.radians(azimuth_deg)
    d_col, d_row = np.sin(az), -np.cos(az)  # row index grows towards the south
    tan_e = np.tan(np.radians(elevation_deg))
    diag = float(np.hypot(*z.shape))
    max_d = min(diag, max(2.0, float(z.max() - z.min()) / (pixel_size_m * tan_e)))
    steps = np.unique(np.concatenate([np.arange(1, 25), np.geomspace(25, max(26, max_d), 90)]).round().astype(int))
    steps = steps[steps <= max_d]
    shadow = np.zeros(z.shape, dtype=bool)
    for d in steps:
        dr, dc = int(round(d * d_row)), int(round(d * d_col))
        dist = float(np.hypot(dr, dc)) * pixel_size_m
        if dist == 0.0:
            continue
        shadow |= (_shifted(z, dr, dc) - z) > dist * tan_e
    return shadow


def compute(z: np.ndarray, pixel_size_m: float, azimuth_deg: float, incidence_deg: float, *,
            cast_shadows: bool = True, stretch: bool = True, z_exaggeration: float = 1.0) -> Hillshade:
    z = np.asarray(z, dtype=np.float32) * np.float32(z_exaggeration)
    elevation = 90.0 - incidence_deg
    night = incidence_deg >= 90.0
    if night:
        return Hillshade(np.zeros(z.shape, np.uint8), 0.0, 1.0 if cast_shadows else 0.0,
                         azimuth_deg % 360.0, incidence_deg, True, False)

    gy, gx = np.gradient(z, pixel_size_m)  # d/d(row), d/d(col)
    dz_de, dz_dn = gx, -gy  # row 0 is north
    inv = 1.0 / np.sqrt(dz_de * dz_de + dz_dn * dz_dn + 1.0)
    inc, az = np.radians(incidence_deg), np.radians(azimuth_deg)
    sx, sy, sz = np.sin(inc) * np.sin(az), np.sin(inc) * np.cos(az), np.cos(inc)
    lit = np.clip((-dz_de * sx - dz_dn * sy + sz) * inv, 0.0, 1.0)

    shadow_fraction = 0.0
    if cast_shadows:
        shadow = cast_shadow_mask(z, pixel_size_m, azimuth_deg, elevation)
        lit = np.where(shadow, 0.0, lit)
        shadow_fraction = float(shadow.mean())

    flat = float(np.cos(inc))
    if stretch:
        top = float(np.percentile(lit, 99.5)) or 1.0
        disp = lit / top
    else:
        disp = lit
    disp = AMBIENT + (1.0 - AMBIENT) * np.clip(disp, 0.0, 1.0)
    return Hillshade((disp * 255.0 + 0.5).astype(np.uint8), flat, shadow_fraction,
                     azimuth_deg % 360.0, incidence_deg, False, stretch)
