"""Metakernel handling.

ESA metakernels use *relative* PATH_VALUES (typically ``'..'``) that are resolved against the
current working directory at FURNSH time, so we temporarily chdir into the metakernel folder.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import spiceypy as sp

from .errors import UtilityError


@dataclass
class KernelInfo:
    metakernel: Path
    total: int
    by_type: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        parts = ", ".join(f"{n} {t}" for t, n in sorted(self.by_type.items()))
        return f"{self.total} kernels ({parts})"


class KernelSession:
    """Owns the SPICE kernel pool for the lifetime of the app (one metakernel at a time)."""

    def __init__(self) -> None:
        self.info: KernelInfo | None = None

    @property
    def loaded(self) -> bool:
        return self.info is not None

    def load(self, metakernel: str | os.PathLike) -> KernelInfo:
        mk = Path(metakernel).expanduser().resolve()
        if not mk.is_file():
            raise UtilityError(f"Metakernel not found:\n{mk}")
        self.unload()
        cwd = os.getcwd()
        try:
            os.chdir(mk.parent)
            sp.furnsh(mk.name)  # short name: avoids FURNSH's 255-char path limit on Windows
        except Exception as exc:  # spiceypy raises SpiceyError subclasses
            sp.kclear()
            raise UtilityError(f"Could not load metakernel:\n{exc}") from exc
        finally:
            os.chdir(cwd)

        by_type: dict[str, int] = {}
        total = sp.ktotal("ALL")
        for i in range(total):
            _file, ftype, _src, _handle = sp.kdata(i, "ALL")
            if ftype == "TEXT":
                ftype = "TXT"
            by_type[ftype] = by_type.get(ftype, 0) + 1
        by_type.pop("META", None)
        self.info = KernelInfo(mk, sum(by_type.values()), by_type)
        return self.info

    def unload(self) -> None:
        sp.kclear()
        self.info = None
