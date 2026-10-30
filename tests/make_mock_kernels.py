"""Synthetic BepiColombo-like kernel set for testing without the real ESA kernels.

* Mercury on a Kepler orbit around the Sun with aphelion #0 at 2027-03-22 08:00 UTC
* "MPO" on a circular 400 km orbit around Mercury (SPK type 5), coverage 2027-06-15 .. 2027-07-15
* nadir-pointing dynamic frame MPO_SPACECRAFT (two-vector), cameras with known tilts:
    STC-H_P700 / STC-H_F420  tilted +20 deg,  STC-L_P700 tilted -20 deg,  HRIC_FPAN nadir
* metakernel with *relative* PATH_VALUES, like the ESA ones
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import spiceypy as sp

GM_SUN = 1.32712440041939e11
GM_MERCURY = 22031.868551
R_MERCURY = 2439.4
ALT_KM = 400.0
MPO_COVERAGE = ("2027-06-15T00:00:00", "2027-07-15T00:00:00")
APH0_UTC = "2027-03-22T08:00:00"

LSK = """KPL/LSK
\\begindata
DELTET/DELTA_T_A       =   32.184
DELTET/K               =    1.657D-3
DELTET/EB              =    1.671D-2
DELTET/M               = (  6.239996D0   1.99096871D-7 )
DELTET/DELTA_AT        = ( 10, @1972-JAN-1   11, @1972-JUL-1   12, @1973-JAN-1   13, @1974-JAN-1
                           14, @1975-JAN-1   15, @1976-JAN-1   16, @1977-JAN-1   17, @1978-JAN-1
                           18, @1979-JAN-1   19, @1980-JAN-1   20, @1981-JUL-1   21, @1982-JUL-1
                           22, @1983-JUL-1   23, @1985-JUL-1   24, @1988-JAN-1   25, @1990-JAN-1
                           26, @1991-JAN-1   27, @1992-JUL-1   28, @1993-JUL-1   29, @1994-JUL-1
                           30, @1996-JAN-1   31, @1997-JUL-1   32, @1999-JAN-1   33, @2006-JAN-1
                           34, @2009-JAN-1   35, @2012-JUL-1   36, @2015-JUL-1   37, @2017-JAN-1 )
\\begintext
"""

PCK = f"""KPL/PCK
\\begindata
BODY10_GM          = ( {GM_SUN} )
BODY199_GM         = ( {GM_MERCURY} )
BODY199_RADII      = ( {R_MERCURY} {R_MERCURY} {R_MERCURY} )
BODY199_POLE_RA    = ( 281.0103  -0.0328  0.0 )
BODY199_POLE_DEC   = (  61.4155  -0.0049  0.0 )
BODY199_PM         = ( 329.5988   6.1385108  0.0 )
\\begintext
"""

# (name, id, parent frame name, tilt deg about Y)
CAMERAS = [
    ("MPO_SIMBIO-SYS_STC-H_P700", -121401, "MPO_SIMBIO-SYS_STC-H", +20.0),
    ("MPO_SIMBIO-SYS_STC-L_P700", -121402, "MPO_SIMBIO-SYS_STC-L", -20.0),
    ("MPO_SIMBIO-SYS_STC-H_F420", -121403, "MPO_SIMBIO-SYS_STC-H", +20.0),
    ("MPO_SIMBIO-SYS_HRIC_FPAN", -121404, "MPO_SIMBIO-SYS_HRIC", 0.0),
]
FRAMES = {"MPO_SIMBIO-SYS_STC-H": (-121411, 20.0), "MPO_SIMBIO-SYS_STC-L": (-121412, -20.0), "MPO_SIMBIO-SYS_HRIC": (-121413, 0.0)}


def _fk() -> str:
    t = ["KPL/FK", "\\begindata",
         "NAIF_BODY_NAME += ( 'MPO' )", "NAIF_BODY_CODE += ( -121 )",
         "FRAME_MPO_SPACECRAFT = -121000", "FRAME_-121000_NAME = 'MPO_SPACECRAFT'",
         "FRAME_-121000_CLASS = 5", "FRAME_-121000_CLASS_ID = -121000", "FRAME_-121000_CENTER = -121",
         "FRAME_-121000_RELATIVE = 'J2000'", "FRAME_-121000_DEF_STYLE = 'PARAMETERIZED'",
         "FRAME_-121000_FAMILY = 'TWO-VECTOR'",
         "FRAME_-121000_PRI_AXIS = 'Z'", "FRAME_-121000_PRI_VECTOR_DEF = 'OBSERVER_TARGET_POSITION'",
         "FRAME_-121000_PRI_OBSERVER = 'MPO'", "FRAME_-121000_PRI_TARGET = 'MERCURY'",
         "FRAME_-121000_PRI_ABCORR = 'NONE'",
         "FRAME_-121000_SEC_AXIS = 'X'", "FRAME_-121000_SEC_VECTOR_DEF = 'OBSERVER_TARGET_VELOCITY'",
         "FRAME_-121000_SEC_OBSERVER = 'MPO'", "FRAME_-121000_SEC_TARGET = 'MERCURY'",
         "FRAME_-121000_SEC_ABCORR = 'NONE'", "FRAME_-121000_SEC_FRAME = 'J2000'"]
    for fname, (fid, tilt) in FRAMES.items():
        t += [f"FRAME_{fname} = {fid}", f"FRAME_{fid}_NAME = '{fname}'", f"FRAME_{fid}_CLASS = 4",
              f"FRAME_{fid}_CLASS_ID = {fid}", f"FRAME_{fid}_CENTER = -121",
              f"TKFRAME_{fid}_RELATIVE = 'MPO_SPACECRAFT'", f"TKFRAME_{fid}_SPEC = 'ANGLES'",
              f"TKFRAME_{fid}_UNITS = 'DEGREES'", f"TKFRAME_{fid}_AXES = ( 1, 2, 3 )",
              f"TKFRAME_{fid}_ANGLES = ( 0.0, {tilt}, 0.0 )"]
    for name, cid, _f, _t in CAMERAS:
        t += [f"NAIF_BODY_NAME += ( '{name}' )", f"NAIF_BODY_CODE += ( {cid} )"]
    t.append("\\begintext")
    return "\n".join(t) + "\n"


def _ik() -> str:
    t = ["KPL/IK", "\\begindata"]
    for name, cid, frame, _tilt in CAMERAS:
        half = 2.5 if "HRIC" not in name else 0.4
        t += [f"INS{cid}_FOV_FRAME = '{frame}'", f"INS{cid}_FOV_SHAPE = 'RECTANGLE'",
              f"INS{cid}_BORESIGHT = ( 0.0 0.0 1.0 )", f"INS{cid}_FOV_CLASS_SPEC = 'ANGLES'",
              f"INS{cid}_FOV_REF_VECTOR = ( 1.0 0.0 0.0 )", f"INS{cid}_FOV_REF_ANGLE = {half}",
              f"INS{cid}_FOV_CROSS_ANGLE = {half}", f"INS{cid}_FOV_ANGLE_UNITS = 'DEGREES'",
              f"INS{cid}_PIXEL_SAMPLES = 2048", f"INS{cid}_PIXEL_LINES = 2048"]
    t.append("\\begintext")
    return "\n".join(t) + "\n"


def build(root: str | Path) -> Path:
    """Write the kernel tree under ``root`` and return the metakernel path."""
    root = Path(root)
    for d in ("lsk", "pck", "fk", "ik", "spk", "mk"):
        (root / "kernels" / d).mkdir(parents=True, exist_ok=True)
    k = root / "kernels"
    (k / "lsk/mock.tls").write_text(LSK)
    (k / "pck/mock.tpc").write_text(PCK)
    (k / "fk/mock.tf").write_text(_fk())
    (k / "ik/mock.ti").write_text(_ik())

    sp.kclear()
    sp.furnsh(str(k / "lsk/mock.tls"))
    aph0 = sp.str2et(APH0_UTC)

    # Mercury about the Sun (perihelion distance 4.6e7 km, e=0.2056 -> ~87.97 d period)
    a, e = 57_909_227.0, 0.205630
    elts = [a * (1 - e), e, 0.5, 1.0, 0.3, math.pi, aph0, GM_SUN]
    ep = np.arange(sp.str2et("2026-12-01T00:00:00"), sp.str2et("2028-01-01T00:00:00"), 86400.0)
    states = np.array([sp.conics(elts, t) for t in ep])
    spk = str(k / "spk/mock.bsp")
    (k / "spk/mock.bsp").unlink(missing_ok=True)
    h = sp.spkopn(spk, "mock", 0)
    sp.spkw09(h, 10, 0, "J2000", ep[0], ep[-1], "SUN", 1, 2, np.array([[1.0, 1.0, 1.0, 0, 0, 0]] * 2), np.array([ep[0], ep[-1]]))  # Sun parked at the SSB
    sp.spkw05(h, 199, 10, "J2000", ep[0], ep[-1], "MERCURY", GM_SUN, len(ep), states, ep)

    # MPO: circular orbit, 400 km altitude
    r = R_MERCURY + ALT_KM
    t0, t1 = (sp.str2et(s) for s in MPO_COVERAGE)
    e2 = np.arange(t0, t1 + 1, 120.0)
    el2 = [r, 0.0, math.radians(80.0), 0.7, 0.0, 0.0, t0, GM_MERCURY]
    st2 = np.array([sp.conics(el2, t) for t in e2])
    sp.spkw05(h, -121, 199, "J2000", e2[0], e2[-1], "MPO", GM_MERCURY, len(e2), st2, e2)
    sp.spkcls(h)
    sp.kclear()

    mk = k / "mk/mock_plan.tm"
    mk.write_text("""KPL/MK
\\begindata
PATH_VALUES  = ( '..' )
PATH_SYMBOLS = ( 'KERNELS' )
KERNELS_TO_LOAD = ( '$KERNELS/lsk/mock.tls', '$KERNELS/pck/mock.tpc', '$KERNELS/fk/mock.tf',
                    '$KERNELS/ik/mock.ti',  '$KERNELS/spk/mock.bsp' )
\\begintext
""")
    return mk
