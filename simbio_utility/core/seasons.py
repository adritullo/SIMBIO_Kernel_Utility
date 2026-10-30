"""Mercury seasons from the Mercury True Anomaly (MTA) and a mission cycle counter.

Default scheme (all editable through ``SeasonConfig`` / ``seasons.json``): the Mercury year is cut into
four 90-degree sectors of true anomaly starting at TA = 135 deg:

    APH  135..225   aphelion window          (centred on TA = 180)
    D2N  225..315   terminator season after aphelion
    PER  315..045   perihelion window        (centred on TA = 0)
    N2D  045..135   terminator season before the next aphelion

The number is the Mercury-year counter: APH0 is the aphelion at the start of the science phase
(``epoch_utc``, ~2027-03-22), APH1 the next one, and so on.  D2N1/PER1/N2D1 are the sectors that follow
APH1 and precede APH2.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SeasonConfig:
    start_ta_deg: float = 135.0
    # (name, offset_from_start_deg_lo, offset_from_start_deg_hi)
    sectors: tuple[tuple[str, float, float], ...] = (
        ("APH", 0.0, 90.0),
        ("D2N", 90.0, 180.0),
        ("PER", 180.0, 270.0),
        ("N2D", 270.0, 360.0),
    )
    epoch_utc: str = "2027-03-22T08:00:00"  # aphelion that is numbered 0
    epoch_ta_deg: float = 180.0
    anomalistic_period_days: float = 87.9693

    @staticmethod
    def from_json(path: str | Path) -> "SeasonConfig":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        base = SeasonConfig()
        sectors = tuple((s["name"], float(s["from"]), float(s["to"])) for s in d["sectors"]) if "sectors" in d else base.sectors
        return SeasonConfig(
            start_ta_deg=float(d.get("start_ta_deg", base.start_ta_deg)),
            sectors=sectors,
            epoch_utc=d.get("epoch_utc", base.epoch_utc),
            epoch_ta_deg=float(d.get("epoch_ta_deg", base.epoch_ta_deg)),
            anomalistic_period_days=float(d.get("anomalistic_period_days", base.anomalistic_period_days)),
        )


@dataclass(frozen=True)
class SeasonResult:
    label: str  # "APH1"
    kind: str  # "APH"
    number: int  # 1
    mta_deg: float
    cycle_ta_deg: float = field(default=0.0, repr=False)  # unwrapped true anomaly


def mean_anomaly_deg(ta_deg: float, ecc: float) -> float:
    nu = math.radians(ta_deg)
    ea = 2.0 * math.atan2(math.sqrt(1 - ecc) * math.sin(nu / 2), math.sqrt(1 + ecc) * math.cos(nu / 2))
    return math.degrees(ea - ecc * math.sin(ea)) % 360.0


def classify(mta_deg: float, ecc: float, et: float, epoch_et: float, cfg: SeasonConfig = SeasonConfig()) -> SeasonResult:
    """Season label for a true anomaly ``mta_deg`` (deg) observed at ``et`` (s past J2000).

    ``epoch_et`` is the ET of the numbered-0 aphelion (``cfg.epoch_utc``); only used to unwrap the
    number of complete Mercury years, so ~day-level accuracy of the epoch/period is plenty.
    """
    ta = mta_deg % 360.0
    m_true = mean_anomaly_deg(ta, ecc)
    m_epoch = mean_anomaly_deg(cfg.epoch_ta_deg, ecc)
    m_est = m_epoch + 360.0 * (et - epoch_et) / (cfg.anomalistic_period_days * 86400.0)
    revs = round((m_est - m_true) / 360.0)
    ta_unwrapped = ta + 360.0 * revs

    rel = (ta - cfg.start_ta_deg) % 360.0
    kind = cfg.sectors[-1][0]
    for name, lo, hi in cfg.sectors:
        if lo <= rel < hi:
            kind = name
            break
    # Year counter: aphelion-centred cycle that contains this epoch, anchored so APH(epoch) = 0.
    anchor = math.floor((cfg.epoch_ta_deg - cfg.start_ta_deg) / 360.0)
    number = math.floor((ta_unwrapped - cfg.start_ta_deg) / 360.0) - anchor
    return SeasonResult(f"{kind}{number}", kind, number, ta, ta_unwrapped)
