"""Mission timeline: STP (Short Term Plan) and MTP (Medium Term Plan) from an ESA event file (.evf).

The EVF holds one ``STP_START`` / ``STP_END`` pair per STP, tagged ``(COUNT = n)``, e.g.::

    14-Mar-2027_02:43:52 STP_START (COUNT = 1)
    21-Mar-2027_10:42:13 STP_END   (COUNT = 1)

Convention (SIMBIO team): an MTP is a block of ``stps_per_mtp`` (= 4) consecutive STPs, so MTP1 = STP1-4,
MTP2 = STP5-8, ... Times are UTC.  Pure python - no SPICE needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import UtilityError

STPS_PER_MTP = 4
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_LINE = re.compile(
    r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})_(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?\s+(STP_START|STP_END)\s*\(\s*COUNT\s*=\s*(\d+)\s*\)", re.M)


@dataclass(frozen=True)
class StpInfo:
    stp: int
    mtp: int
    stp_in_mtp: int  # 1..stps_per_mtp
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"MTP{self.mtp} · STP{self.stp}"

    @property
    def window(self) -> str:
        f = "%Y-%m-%d %H:%M:%S"
        return f"{self.start.strftime(f)} → {self.end.strftime(f)} UTC"


class StpTable:
    def __init__(self, stps: dict[int, tuple[datetime, datetime]], stps_per_mtp: int = STPS_PER_MTP, source: str = "") -> None:
        if not stps:
            raise UtilityError("No STP_START/STP_END events found in the event file.")
        self.stps_per_mtp = stps_per_mtp
        self.source = source
        self._nums = sorted(stps)
        self._stps = stps

    # ---- construction
    @staticmethod
    def from_text(text: str, stps_per_mtp: int = STPS_PER_MTP, source: str = "") -> "StpTable":
        starts: dict[int, datetime] = {}
        ends: dict[int, datetime] = {}
        for d, mon, y, hh, mm, ss, frac, kind, count in _LINE.findall(text):
            month = _MONTHS.get(mon.lower())
            if month is None:
                raise UtilityError(f"Unknown month '{mon}' in the event file.")
            micro = int((frac or "0").ljust(6, "0")[:6])
            t = datetime(int(y), month, int(d), int(hh), int(mm), int(ss), micro)
            (starts if kind == "STP_START" else ends)[int(count)] = t
        stps = {n: (starts[n], ends[n]) for n in starts if n in ends}
        if not stps:
            raise UtilityError("No complete STP_START/STP_END pairs found in the event file.")
        return StpTable(stps, stps_per_mtp, source)

    @staticmethod
    def from_file(path: str | Path, stps_per_mtp: int = STPS_PER_MTP) -> "StpTable":
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise UtilityError(f"Cannot read event file '{p}': {exc}") from exc
        return StpTable.from_text(text, stps_per_mtp, source=str(p))

    # ---- queries
    def __len__(self) -> int:
        return len(self._stps)

    @property
    def n_mtp(self) -> int:
        return self.mtp_of(self._nums[-1])

    @property
    def span(self) -> tuple[datetime, datetime]:
        return self._stps[self._nums[0]][0], self._stps[self._nums[-1]][1]

    def mtp_of(self, stp: int) -> int:
        return (stp - 1) // self.stps_per_mtp + 1

    def info(self, stp: int) -> StpInfo:
        s, e = self._stps[stp]
        return StpInfo(stp, self.mtp_of(stp), (stp - 1) % self.stps_per_mtp + 1, s, e)

    def lookup(self, utc: datetime) -> StpInfo | None:
        """STP containing ``utc``; a STP lasts until the next one starts (so 1-second gaps belong to the next STP)."""
        first, last_end = self.span
        if utc < first or utc >= last_end:
            return None
        chosen = None
        for n in self._nums:  # ~150 entries: linear scan is fine
            if self._stps[n][0] <= utc:
                chosen = n
            else:
                break
        return self.info(chosen) if chosen is not None else None

    def summary(self) -> str:
        a, b = self.span
        return f"{len(self)} STPs · {self.n_mtp} MTPs · {a:%Y-%m-%d} → {b:%Y-%m-%d}"
