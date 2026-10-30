"""Persistent user settings (QSettings: registry on Windows, ini elsewhere)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

from .core.geometry import GeometrySettings
from .core.seasons import SeasonConfig
from .core.stp import StpTable
from .resources import resource_path

BUILTIN_EVF = "stp_default.evf"
_STP_CACHE: dict[tuple[str, float], StpTable] = {}


class AppConfig:
    def __init__(self) -> None:
        # SKU_SETTINGS_FILE redirects settings to an ini file (used by the tests so they never touch the user's registry)
        ini = os.environ.get("SKU_SETTINGS_FILE")
        self._s = QSettings(ini, QSettings.IniFormat) if ini else QSettings("INAF", "SimbioKernelUtility")

    def get(self, key: str, default=""):
        return self._s.value(key, default)

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)

    def get_bool(self, key: str, default: bool) -> bool:
        v = self._s.value(key, default)
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")

    @property
    def abcorr(self) -> str:
        return str(self.get("abcorr", "LT+S"))

    @property
    def lon_domain(self) -> str:
        return str(self.get("lon_domain", "180"))

    @property
    def season_json(self) -> str:
        return str(self.get("season_json", ""))

    @property
    def stp_evf(self) -> str:
        """User-selected EVF path; empty string = built-in timeline."""
        return str(self.get("stp_evf", ""))

    def stp_table(self) -> StpTable | None:
        """Timeline from the user's EVF if set and valid, otherwise the built-in one (cached by path + mtime)."""
        for path in (self.stp_evf, str(resource_path(BUILTIN_EVF))):
            if not path or not Path(path).is_file():
                continue
            key = (path, Path(path).stat().st_mtime)
            if key not in _STP_CACHE:
                try:
                    _STP_CACHE[key] = StpTable.from_file(path)
                except Exception:
                    continue
            return _STP_CACHE[key]
        return None

    def geometry_settings(self) -> GeometrySettings:
        cfg = SeasonConfig()
        p = self.season_json
        if p and Path(p).is_file():
            cfg = SeasonConfig.from_json(p)
        return GeometrySettings(abcorr=self.abcorr, lon_domain=self.lon_domain, seasons=cfg, stp=self.stp_table())
