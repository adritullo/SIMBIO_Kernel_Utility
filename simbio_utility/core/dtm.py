"""Minimal GeoTIFF DTM reader (tifffile only - no GDAL needed, keeps the .exe small).

The DTM is used as an *illustrative reference terrain* for the hillshade: only its relief and pixel
size matter, it is never georeferenced onto Mercury.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile

from .errors import UtilityError

logging.getLogger("tifffile").setLevel(logging.ERROR)  # noisy GDAL_NODATA float32 warning


@dataclass
class Dtm:
    z: np.ndarray  # float32, metres, row 0 = north
    pixel_size_m: float
    path: str
    nodata_fraction: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape

    @property
    def relief_m(self) -> float:
        return float(self.z.max() - self.z.min())


def load_dtm(path: str | Path, max_dim: int = 1400, default_pixel_size_m: float = 5.0) -> Dtm:
    """Read the first band, mask no-data, block-average down so the longest side is <= ``max_dim``."""
    p = Path(path)
    if not p.is_file():
        raise UtilityError(f"DTM not found:\n{p}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with tifffile.TiffFile(p) as tf:
                page = tf.pages[0]
                arr = np.asarray(page.asarray(), dtype=np.float32)
                scale_tag = page.tags.get("ModelPixelScaleTag")
                scale = tuple(scale_tag.value) if scale_tag is not None else None
                nodata_tag = page.tags.get(42113)
                nodata = float(str(nodata_tag.value).strip("\x00")) if nodata_tag is not None else None
    except Exception as exc:
        hint = ""
        if "imagecodecs" in str(exc) or "COMPRESSION" in str(exc).upper():
            hint = ("\nThis compression needs the optional 'imagecodecs' package. Either install it, or re-save the DTM "
                    "uncompressed / DEFLATE, e.g.  gdal_translate -co COMPRESS=DEFLATE in.tif out.tif")
        raise UtilityError(f"Cannot read DTM '{p.name}': {exc}{hint}") from exc

    if arr.ndim == 3:
        arr = arr[..., 0] if arr.shape[-1] <= 4 else arr[0]
    bad = ~np.isfinite(arr) | (arr < -1e30) | (arr > 1e30)
    if nodata is not None and np.isfinite(nodata):
        bad |= arr == np.float32(nodata)
    if bad.all():
        raise UtilityError("The DTM contains no valid elevation values.")
    frac = float(bad.mean())
    if frac:
        arr = np.where(bad, np.float32(arr[~bad].mean()), arr)

    ps = float(scale[0]) if scale and scale[0] > 0 else default_pixel_size_m
    if ps < 0.01:  # geographic degrees -> approximate metres, good enough for illustration
        ps = float(np.radians(ps) * 2_439_400.0)

    f = int(np.ceil(max(arr.shape) / max_dim)) if max_dim else 1
    if f > 1:
        h, w = (arr.shape[0] // f) * f, (arr.shape[1] // f) * f
        arr = arr[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3), dtype=np.float32)
        ps *= f
    return Dtm(np.ascontiguousarray(arr, dtype=np.float32), ps, str(p), frac)


def resample_to_pixel_size(z: np.ndarray, ps_in: float, ps_out: float) -> tuple[np.ndarray, float]:
    """Resample a DEM so that one pixel spans ``ps_out`` metres (area-average when coarsening).

    * ps_out > ps_in: integer block-mean (box filter) followed by a bilinear step for the remaining fraction,
      so detail below the new pixel size is averaged away like a real instrument pixel would.
    * ps_out <= ps_in: the DEM is returned unchanged - it cannot contain detail finer than its own pixel.
    Returns (array, pixel size actually used).
    """
    if ps_out <= ps_in * 1.001:
        return z, ps_in
    f = ps_out / ps_in
    n = int(np.floor(f))
    zz = z
    if n > 1:
        h, w = (zz.shape[0] // n) * n, (zz.shape[1] // n) * n
        zz = zz[:h, :w].reshape(h // n, n, w // n, n).mean(axis=(1, 3), dtype=np.float32)
    scale = f / n  # residual pixel-size ratio, in [1, 2)
    if scale > 1.0005:
        zz = _linear_resample(zz, scale)
    return np.ascontiguousarray(zz, dtype=np.float32), ps_out


def _linear_resample(z: np.ndarray, scale: float) -> np.ndarray:
    def idx(n_in: int, n_out: int):
        x = np.clip((np.arange(n_out) + 0.5) * scale - 0.5, 0, n_in - 1)
        i0 = np.floor(x).astype(int)
        return i0, np.minimum(i0 + 1, n_in - 1), (x - i0).astype(np.float32)

    h, w = int(z.shape[0] / scale), int(z.shape[1] / scale)
    r0, r1, wr = idx(z.shape[0], h)
    c0, c1, wc = idx(z.shape[1], w)
    rows = z[r0] * (1 - wr)[:, None] + z[r1] * wr[:, None]
    return rows[:, c0] * (1 - wc)[None, :] + rows[:, c1] * wc[None, :]


def fit_max_dim(z: np.ndarray, ps: float, max_dim: int) -> tuple[np.ndarray, float]:
    """Block-average so the longest side is <= max_dim (display-speed limit used when scaling is off)."""
    f = int(np.ceil(max(z.shape) / max_dim)) if max_dim else 1
    if f <= 1:
        return z, ps
    h, w = (z.shape[0] // f) * f, (z.shape[1] // f) * f
    return np.ascontiguousarray(z[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3), dtype=np.float32)), ps * f
