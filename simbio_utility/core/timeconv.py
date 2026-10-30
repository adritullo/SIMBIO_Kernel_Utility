"""UTC <-> ET (TDB seconds past J2000) conversions. Requires an LSK in the kernel pool."""
from __future__ import annotations

import re

import spiceypy as sp

from .errors import TimeParseError

_ISO_SPACE_T = re.compile(r"(\d)\s*T\s*(\d)")


def normalize_utc_string(text: str) -> str:
    """Make common ISO variants digestible by STR2ET ('2027-05-18 T02:10:30', trailing 'Z')."""
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1]
    return _ISO_SPACE_T.sub(r"\1T\2", s, count=1)


def utc_to_et(text: str) -> float:
    s = normalize_utc_string(text)
    if not s:
        raise TimeParseError("Empty time string.")
    try:
        return sp.str2et(s)
    except Exception as exc:
        raise TimeParseError(f"Cannot parse '{text}' as a time.\n{_first_line(exc)}") from exc


def et_to_utc(et: float, precision: int = 3) -> str:
    """ISO calendar UTC string, e.g. 2027-04-06T07:48:34.000"""
    return sp.et2utc(et, "ISOC", precision)


def et_to_utc_doy(et: float, precision: int = 3) -> str:
    """ISO day-of-year UTC string, e.g. 2027-096T07:48:34.000"""
    return sp.et2utc(et, "ISOD", precision)


def et_to_tdb(et: float, precision: int = 3) -> str:
    frac = "#" * precision
    return sp.timout(et, f"YYYY-MM-DD HR:MN:SC.{frac} ::TDB" if precision else "YYYY-MM-DD HR:MN:SC ::TDB")


def _first_line(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else exc.__class__.__name__
