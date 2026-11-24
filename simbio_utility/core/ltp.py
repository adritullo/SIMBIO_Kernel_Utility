"""Long Term Plans (LTP) from the BepiColombo planning-cycle file (``bc_ltp_mtp_stp_*.def``).

Each data line is one STP::

    # STP  MTP  orbit_start  orbit_end   #  LTP  STP_start             STP_end
    0001   001  00001        00070       #  001  14-Mar-2027_02:43:52  21-Mar-2027_02:26:11

An LTP spans from the start of its first STP to the end of its last one.  Times are UTC.  Pure python.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import UtilityError

DEFAULT_FILE = "bc_ltp_mtp_stp_test_v01.def"
_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+#\s*(\d+)\s+(\S+)\s+(\S+)\s*$")


def _when(text: str) -> datetime:
    return datetime.strptime(text, "%d-%b-%Y_%H:%M:%S")


@dataclass(frozen=True)
class Ltp:
    number: int
    start: datetime
    end: datetime
    stps: tuple[int, int]  # first, last STP
    mtps: tuple[int, int]

    @property
    def start_utc(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def end_utc(self) -> str:
        return self.end.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def label(self) -> str:
        return (f"LTP{self.number}: {self.start:%Y-%m-%d} → {self.end:%Y-%m-%d}  "
                f"(MTP{self.mtps[0]}–{self.mtps[1]}, STP{self.stps[0]}–{self.stps[1]})")


def parse_ltps(text: str) -> dict[int, Ltp]:
    rows: dict[int, list[tuple[int, int, datetime, datetime]]] = {}
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        stp, mtp, _o1, _o2, ltp = (int(m.group(i)) for i in range(1, 6))
        try:
            rows.setdefault(ltp, []).append((stp, mtp, _when(m.group(6)), _when(m.group(7))))
        except ValueError as exc:
            raise UtilityError(f"Bad date in the LTP file: {line.strip()}") from exc
    if not rows:
        raise UtilityError("No LTP/STP rows found in the planning-cycle file.")
    out = {}
    for n, rs in sorted(rows.items()):
        out[n] = Ltp(n, min(r[2] for r in rs), max(r[3] for r in rs),
                     (min(r[0] for r in rs), max(r[0] for r in rs)), (min(r[1] for r in rs), max(r[1] for r in rs)))
    return out


def load_ltps(path: str | Path | None = None) -> dict[int, Ltp]:
    if path is None:
        from ..resources import resource_path
        path = resource_path(DEFAULT_FILE)
    return parse_ltps(Path(path).read_text(encoding="utf-8", errors="replace"))
