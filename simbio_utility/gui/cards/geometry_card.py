from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...core import dtm as dtm_mod, hillshade, instruments, timeconv
from ...core.errors import NoIntercept, UtilityError, spice_message
from ...core.geometry import GeometryResult, compute as compute_geometry
from ...resources import default_dtm, dtm_family
from .. import theme
from ..widgets import Debouncer, ImageView, Panel, Segmented, Tile, copy_to_clipboard, label
from .base import Card

# (key, caption, unit, formatter, tooltip)
METRICS = [
    ("resolution_m_px", "Ground resolution", "m/px", lambda r: f"{r.resolution_m_px:.2f}", "Central pixel: slant range × IFOV / cos(emission)"),
    ("altitude_km", "Flight altitude", "km", lambda r: f"{r.altitude_km:.2f}", "Above the reference ellipsoid at the sub-spacecraft point"),
    ("orbital_velocity_kms", "Orbital velocity", "km/s", lambda r: f"{r.orbital_velocity_kms:.4f}", "Inertial speed of the spacecraft relative to Mercury (J2000)"),
    ("lat_deg", "Latitude · central px", "°", lambda r: f"{r.lat_deg:.4f}", "Planetocentric, boresight intercept"),
    ("lon_deg", "Longitude · central px", "°E", lambda r: f"{r.lon_deg:.4f}", "East-positive, boresight intercept"),
    ("slant_range_km", "Slant range", "km", lambda r: f"{r.slant_range_km:.2f}", "Spacecraft → central pixel distance"),
    ("sc_lat_deg", "Sub-S/C latitude", "°", lambda r: f"{r.sc_lat_deg:.4f}", "Planetocentric, nearest point on the ellipsoid"),
    ("sc_lon_deg", "Sub-S/C longitude", "°E", lambda r: f"{r.sc_lon_deg:.4f}", "East-positive"),
    ("incidence_deg", "Solar incidence", "°", lambda r: f"{r.incidence_deg:.3f}", "Sun – local vertical angle at the central pixel (≥ 90° = night)"),
    ("azimuth_deg", "Solar azimuth", "°", lambda r: f"{r.azimuth_deg:.3f}", "Direction towards the Sun, clockwise from local north"),
    ("phase_deg", "Phase", "°", lambda r: f"{r.phase_deg:.3f}", "Sun – surface point – spacecraft angle"),
    ("emission_deg", "Emission", "°", lambda r: f"{r.emission_deg:.3f}", "Local vertical – spacecraft angle"),
]


@dataclass
class _HsOut:
    hs: hillshade.Hillshade
    pixel_size_m: float
    relief_m: float
    note: str
    shape: tuple


class _HsSignals(QObject):
    done = Signal(int, object)  # job id, _HsOut
    failed = Signal(int, str)
    latest = 0  # id of the newest job; older queued jobs skip their work (rapid stepping / auto-repeat)


class _HsJob(QRunnable):
    """numpy-only work (no SPICE calls here) so it can safely run in a pool thread."""

    cache: dict[str, dtm_mod.Dtm] = {}

    def __init__(self, signals: _HsSignals, job_id: int, path: str, az: float, inc: float, shadows: bool,
                 res_m: float | None) -> None:
        super().__init__()
        self.id, self.path, self.az, self.inc, self.shadows, self.res = job_id, path, az, inc, shadows, res_m
        self.signals = signals  # shared, long-lived (owned by the card) - never one QObject per job

    def run(self) -> None:
        if self.id != self.signals.latest:
            return  # superseded while waiting in the queue
        try:
            d = self.cache.get(self.path)
            if d is None:
                d = self.cache[self.path] = dtm_mod.load_dtm(self.path, max_dim=0)  # keep native resolution
            ps0 = d.pixel_size_m
            if self.res is not None and math.isfinite(self.res) and self.res > 0:
                # never shrink below ~16 px on the short side (very coarse instruments / grazing views)
                res = min(self.res, min(d.shape) * ps0 / 16.0)
                z, ps = dtm_mod.resample_to_pixel_size(d.z, ps0, res)
                if ps > ps0 * 1.001:
                    note = (f"DTM rescaled to the instrument ground resolution ({self.res:.2f} m/px; native {ps0:g} m/px, "
                            f"x{res / ps0:.1f} coarser) so relief and shadow sizes match what the camera resolves")
                    if res < self.res:
                        note += " [limited to keep the preview usable]"
                else:
                    note = (f"instrument resolution ({self.res:.2f} m/px) is finer than the DTM ({ps0:g} m/px): "
                            "DTM kept at its native pixel size")
            else:
                z, ps = dtm_mod.fit_max_dim(d.z, ps0, 1400)
                note = f"original DTM pixel size ({ps:g} m/px), not scaled to the instrument"
            hs = hillshade.compute(z, ps, self.az, self.inc, cast_shadows=self.shadows)
            self.signals.done.emit(self.id, _HsOut(hs, ps, d.relief_m, note, z.shape))
        except Exception as exc:
            try:
                self.signals.failed.emit(self.id, str(exc))
            except RuntimeError:  # window closed while rendering
                pass


class GeometryCard(Card):
    title = "Observation Geometry"
    subtitle = "Season, MTA, resolution, illumination angles for one epoch"
    glyph = "◎"

    def build(self, root: QWidget) -> None:
        self.result: GeometryResult | None = None
        self._cameras: list[instruments.Camera] = []
        self._job = 0
        self._pool = QThreadPool.globalInstance()
        self._hs_signals = _HsSignals()
        self._hs_signals.done.connect(self._hs_done)
        self._hs_signals.failed.connect(self._hs_failed)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        # ---------------- inputs ----------------
        left = Panel("Inputs")
        left.setFixedWidth(460)
        left.body.addWidget(label("Channel", "muted"))
        self.channel = QComboBox()
        left.body.addWidget(self.channel)
        left.body.addWidget(label("Filter", "muted"))
        self.filter = QComboBox()
        left.body.addWidget(self.filter)
        self.cam_name = label("", "small", selectable=True)
        self.cam_name.setProperty("role", "small")
        left.body.addWidget(self.cam_name)

        left.body.addSpacing(6)
        trow = QHBoxLayout()
        trow.addWidget(label("Epoch", "muted"))
        trow.addStretch(1)
        self.mode = Segmented(["UTC", "ET"])
        trow.addWidget(self.mode)
        left.body.addLayout(trow)
        self.time_in = QLineEdit()
        self.time_in.setProperty("mono", True)
        self.time_in.setPlaceholderText("2027-04-06T07:48:34.000")
        self.time_in.setStyleSheet("padding: 8px 8px;")
        step_row = QHBoxLayout()
        step_row.setSpacing(4)
        self.step_btns: list[tuple[QPushButton, float]] = []

        def _step_button(text: str, seconds: float, tip: str) -> QPushButton:
            b = QPushButton(text)
            b.setFixedWidth(40 if len(text) > 1 else 30)
            b.setStyleSheet("padding: 8px 0; font-weight: 700;")
            b.setToolTip(tip + "  (hold to repeat)")
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(450)
            b.setAutoRepeatInterval(150)
            b.clicked.connect(lambda _=False, s=seconds: self._step(s))
            self.step_btns.append((b, seconds))
            return b

        step_row.addWidget(_step_button("«««", -3600.0, "Back 1 hour"))
        step_row.addWidget(_step_button("«", -60.0, "Back 1 minute"))
        step_row.addWidget(_step_button("‹", -1.0, "Back 1 second"))
        step_row.addWidget(self.time_in, 1)
        step_row.addWidget(_step_button("›", 1.0, "Forward 1 second"))
        step_row.addWidget(_step_button("»", 60.0, "Forward 1 minute"))
        step_row.addWidget(_step_button("»»»", 3600.0, "Forward 1 hour"))
        left.body.addLayout(step_row)
        self.time_echo = label("", "small", selectable=True)
        left.body.addWidget(self.time_echo)

        left.body.addSpacing(6)
        self.chk_hs = QCheckBox("Illustrative hillshade")
        self.chk_hs.setChecked(self.config.get_bool("hs_enabled", True))
        self.chk_shadow = QCheckBox("Include cast shadows")
        self.chk_shadow.setChecked(self.config.get_bool("hs_shadows", True))
        self.chk_scale = QCheckBox("Scale DTM to ground resolution")
        self.chk_scale.setChecked(self.config.get_bool("hs_scale", True))
        self.chk_scale.setToolTip("ON: DTM pixels are resampled to the instrument ground resolution, so relief and shadows have "
                                  "the size the camera would resolve.\nOFF: original DTM pixel size.")
        left.body.addWidget(self.chk_hs)
        left.body.addWidget(self.chk_shadow)
        left.body.addWidget(self.chk_scale)
        self.dtm_label = label("Reference DTM", "muted")
        left.body.addWidget(self.dtm_label)
        drow = QHBoxLayout()
        self._dtm_family: str | None = None
        self.dtm_path = QLineEdit()
        self.dtm_path.setProperty("mono", True)
        self.dtm_path.setToolTip("GeoTIFF used only as generic reference relief (never placed on Mercury).\n"
                                 "Switches automatically with the channel (HRIC / STC+VIHI); edit it to use your own file - "
                                 "the choice is remembered per family. Clear the field to restore the bundled DTM.")
        bd = QPushButton("…")
        bd.setFixedWidth(40)
        bd.setStyleSheet("padding: 8px 0;")
        bd.clicked.connect(self._browse_dtm)
        self.dtm_path.editingFinished.connect(self._dtm_edited)
        drow.addWidget(self.dtm_path, 1)
        drow.addWidget(bd)
        left.body.addLayout(drow)

        left.body.addSpacing(8)
        self.btn = QPushButton("Compute")
        self.btn.setProperty("primary", True)
        self.btn.setDefault(True)
        left.body.addWidget(self.btn)
        brow = QHBoxLayout()
        self.btn_copy = QPushButton("Copy all")
        self.btn_export = QPushButton("Export…")
        brow.addWidget(self.btn_copy)
        brow.addWidget(self.btn_export)
        left.body.addLayout(brow)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        left.body.addWidget(self.error)
        left.body.addStretch(1)
        outer.addWidget(left)

        # ---------------- results ----------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        scroll.setWidget(host)
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(14)

        head = Panel()
        head.body.setContentsMargins(22, 16, 22, 16)
        hl = QHBoxLayout()
        hl.setSpacing(22)
        sb = QVBoxLayout()
        sb.setSpacing(0)
        sb.addWidget(label("SEASON", "tilelabel"))
        self.season = label("—", "h1")
        self.season.setStyleSheet("font-size: 38px; font-weight: 700;")
        self.season_desc = label("Run a computation", "muted")
        sb.addWidget(self.season)
        sb.addWidget(self.season_desc)
        hl.addLayout(sb)
        self.t_mta = Tile("MTA · true anomaly", "°", "Mercury True Anomaly (heliocentric orbit, ECLIPJ2000)")
        self.t_mta.setMinimumWidth(150)
        self.t_plan = Tile("Mission plan", "", "MTP = 4 consecutive STPs (MTP1 = STP1-4 ...), from the event file in Settings")
        self.t_plan.setMinimumWidth(190)
        hl.addWidget(self.t_mta, 1)
        hl.addWidget(self.t_plan, 1)
        head.body.addLayout(hl)
        self.echo = label("", "small", wrap=True, selectable=True)
        head.body.addWidget(self.echo)
        col.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles: dict[str, Tile] = {}
        for i, (key, cap, unit, _fmt, tip) in enumerate(METRICS):
            t = Tile(cap, unit, tip)
            self.tiles[key] = t
            grid.addWidget(t, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        col.addLayout(grid)
        self.note = label("", "note", wrap=True)
        col.addWidget(self.note)

        self.hs_panel = Panel("Illumination preview · reference terrain")
        self.view = ImageView()
        self.view.setMinimumHeight(360)
        self.hs_panel.body.addWidget(self.view, 1)
        self.hs_caption = label("", "note", wrap=True)
        self.hs_panel.body.addWidget(self.hs_caption)
        row = QHBoxLayout()
        self.btn_png = QPushButton("Save PNG…")
        self.btn_png.setEnabled(False)
        row.addWidget(self.btn_png)
        row.addStretch(1)
        self.hs_panel.body.addLayout(row)
        col.addWidget(self.hs_panel, 1)
        outer.addWidget(scroll, 1)

        # ---------------- wiring ----------------
        self.channel.currentIndexChanged.connect(self._fill_filters)
        self.filter.currentIndexChanged.connect(self._camera_changed)
        self.mode.changed.connect(self._mode_changed)
        self._echo = Debouncer(self._update_echo, 150)
        self.time_in.textChanged.connect(self._echo)
        self.time_in.returnPressed.connect(self.compute)
        self.btn.clicked.connect(self.compute)
        self.btn_copy.clicked.connect(self._copy_all)
        self.btn_export.clicked.connect(self._export)
        self.btn_png.clicked.connect(self._save_png)
        self.chk_hs.toggled.connect(self._hs_toggled)
        self.chk_shadow.toggled.connect(lambda *_: self._hs_toggled(self.chk_hs.isChecked()))
        self.chk_scale.toggled.connect(lambda *_: self._hs_toggled(self.chk_hs.isChecked()))
        self.hs_panel.setVisible(self.chk_hs.isChecked())

    # ------------------------------------------------------------------ cameras
    def kernels_changed(self) -> None:
        self.result = None
        self._cameras = instruments.discover_cameras()
        want = str(self.config.get("last_camera", "MPO_SIMBIO-SYS_STC-H_P700"))
        self.channel.blockSignals(True)
        self.channel.clear()
        for ch in dict.fromkeys(c.channel for c in self._cameras):
            self.channel.addItem(ch)
        self.channel.blockSignals(False)
        cam = next((c for c in self._cameras if c.name == want), self._cameras[0] if self._cameras else None)
        if cam:
            self.channel.setCurrentText(cam.channel)
        self._fill_filters(prefer=cam.filter if cam else None)
        unavailable = bool(self._cameras) and not self._cameras[0].available
        self.note.setText("No SIMBIO-SYS camera found in the kernel pool (IK/FK not in the metakernel?). "
                          "Showing the known list; computing will fail until the instrument kernels are loaded." if unavailable else "")
        self._clear_results()

    def _fill_filters(self, *_a, prefer: str | None = None) -> None:
        ch = self.channel.currentText()
        self.filter.blockSignals(True)
        self.filter.clear()
        for c in self._cameras:
            if c.channel == ch:
                self.filter.addItem(c.filter, c.name)
        if prefer:
            self.filter.setCurrentText(prefer)
        self.filter.blockSignals(False)
        self._camera_changed()

    def _camera_changed(self, *_a) -> None:
        self.cam_name.setText(self.filter.currentData() or "")
        self._apply_family_dtm()

    def _apply_family_dtm(self) -> None:
        """Show the reference DTM of the selected channel's family (user override if any, else the bundled one).

        Only the selection changes here; the DTM is used by the next Compute."""
        fam = dtm_family(self.channel.currentText())
        if fam == self._dtm_family:
            return
        self._dtm_family = fam
        own = str(self.config.get(f"dtm_path_{fam}", "") or "").strip()
        self.dtm_path.setText(own or str(default_dtm(fam)))
        self.dtm_label.setText("Reference DTM · HRIC" if fam == "HRIC" else "Reference DTM · STC / VIHI")

    def _store_dtm(self, path: str) -> None:
        """Remember a user-chosen DTM for the current family (the bundled one is the implicit default)."""
        fam = self._dtm_family or dtm_family(self.channel.currentText())
        path = path.strip()
        is_default = not path or Path(path) == default_dtm(fam)
        self.config.set(f"dtm_path_{fam}", "" if is_default else path)
        if not path:
            self.dtm_path.setText(str(default_dtm(fam)))

    def _dtm_edited(self) -> None:
        self._store_dtm(self.dtm_path.text())

    def camera(self) -> str:
        return self.filter.currentData() or ""

    # ------------------------------------------------------------------ time
    def set_et(self, et: float) -> None:
        self.mode.set_index(1)
        self.time_in.setPlaceholderText("866764869.184")
        self.time_in.setText(f"{et:.6f}")

    def _step(self, seconds: float) -> None:
        """Move the epoch by ``seconds`` (ET arithmetic, so leap seconds are handled) and recompute."""
        try:
            et = self._parse_time() + seconds
            if self.mode.index() == 1:
                text = f"{et:.6f}"
            else:
                m = re.search(r"\.(\d+)\s*$", self.time_in.text().strip())
                text = timeconv.et_to_utc(et, min(6, max(3, len(m.group(1)) if m else 3)))
        except UtilityError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:
            self._fail(spice_message(exc))
            return
        self.time_in.setText(text)
        self.compute()

    def _mode_changed(self, idx: int) -> None:
        self.time_in.setPlaceholderText("866764869.184" if idx else "2027-04-06T07:48:34.000")
        self._update_echo()

    def _parse_time(self) -> float:
        text = self.time_in.text().strip()
        if not text:
            raise UtilityError("Enter an epoch (UTC string or ET seconds).")
        if self.mode.index() == 1:
            try:
                return float(text.replace(",", "."))
            except ValueError as exc:
                raise UtilityError(f"'{text}' is not a valid ET (seconds past J2000 TDB).") from exc
        return timeconv.utc_to_et(text)

    def _update_echo(self) -> None:
        if not self.time_in.text().strip():
            self.time_echo.setText("")
            return
        try:
            et = self._parse_time()
            self.time_echo.setText(f"= ET {et:.6f}" if self.mode.index() == 0 else f"= UTC {timeconv.et_to_utc(et, 3)}")
        except UtilityError:
            self.time_echo.setText("")
        except Exception as exc:
            self.time_echo.setText(spice_message(exc))

    # ------------------------------------------------------------------ compute
    def compute(self) -> None:
        self.error.hide()
        try:
            et = self._parse_time()
            cam = self.camera()
            if not cam:
                raise UtilityError("No camera selected.")
            res = compute_geometry(cam, et, self.config.geometry_settings())
        except NoIntercept as exc:
            self._fail(str(exc) + "\nTry another epoch (the instrument may not be pointing at the planet).")
            return
        except UtilityError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:
            self._fail(spice_message(exc))
            return
        self.config.set("last_camera", cam)
        self.result = res
        self._show(res)
        if self.chk_hs.isChecked():
            self._start_hillshade(res)

    def _fail(self, msg: str) -> None:
        self.error.setText(msg)
        self.error.show()
        self._clear_results()

    def _clear_results(self) -> None:
        self.result = None
        self.season.setText("—")
        self.season.setStyleSheet("font-size: 38px; font-weight: 700;")
        self.season_desc.setText("Run a computation")
        self.t_mta.clear()
        self.t_plan.clear()
        self.t_plan.set_hint("MTP = 4 consecutive STPs (MTP1 = STP1-4 ...), from the event file in Settings")
        for t in self.tiles.values():
            t.clear()
        self.echo.setText("")
        self.view.set_image(np.zeros((2, 2), "uint8"), None, 1.0, "")
        self.hs_caption.setText("")
        self.btn_png.setEnabled(False)
        self._job += 1

    def _show(self, r: GeometryResult) -> None:
        color = theme.SEASON_COLORS.get(r.season_kind, theme.TEXT)
        self.season.setText(r.season)
        self.season.setStyleSheet(f"font-size: 38px; font-weight: 700; color: {color};")
        self.season_desc.setText(theme.SEASON_NAMES.get(r.season_kind, r.season_kind))
        self.t_mta.set_value(f"{r.mta_deg:.3f}")
        for key, _cap, _unit, fmt, _tip in METRICS:
            self.tiles[key].set_value(fmt(r))
        self.echo.setText(f"UTC {r.utc}   ·   ET {r.et:.6f}   ·   {r.camera}")
        if r.mtp is not None:
            self.t_plan.set_value(f"MTP{r.mtp} · STP{r.stp}", f"MTP{r.mtp} STP{r.stp}")
            self.t_plan.set_hint(f"STP{r.stp} is #{r.stp_in_mtp} of its MTP\n{r.stp_window}")
        else:
            self.t_plan.set_value("—", "")
            self.t_plan.set_hint("Epoch is outside the STP timeline of the event file")
        notes = [f"IFOV {r.ifov_urad:.2f} µrad ({r.ifov_source}); aberration correction {r.abcorr}."]
        if r.is_night:
            notes.insert(0, "Central pixel is on the night side (incidence ≥ 90°).")
        self.note.setText(" ".join(notes))

    # ------------------------------------------------------------------ hillshade
    def _hs_toggled(self, on: bool) -> None:
        self.config.set("hs_enabled", on)
        self.config.set("hs_shadows", self.chk_shadow.isChecked())
        self.hs_panel.setVisible(on)
        if on and self.result is not None:
            self._start_hillshade(self.result)

    def _browse_dtm(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Reference DTM", str(Path(self.dtm_path.text()).parent), "GeoTIFF (*.tif *.tiff);;All files (*)")
        if p:
            self.dtm_path.setText(p)
            self._store_dtm(p)
            if self.chk_hs.isChecked() and self.result is not None:
                self._start_hillshade(self.result)

    def _start_hillshade(self, r: GeometryResult) -> None:
        self._job += 1
        self._hs_signals.latest = self._job
        self.hs_caption.setStyleSheet("")
        self.hs_caption.setText("Rendering…")
        self.config.set("hs_scale", self.chk_scale.isChecked())
        res = r.resolution_m_px if self.chk_scale.isChecked() else None
        job = _HsJob(self._hs_signals, self._job, self.dtm_path.text().strip(), r.azimuth_deg, r.incidence_deg, self.chk_shadow.isChecked(), res)
        self._pool.start(job)

    def _hs_done(self, job_id: int, out: _HsOut) -> None:
        if job_id != self._job:
            return
        hs, ps, relief = out.hs, out.pixel_size_m, out.relief_m
        msg = "Night side · Sun below the local horizon" if hs.night else ""
        self.view.set_image(hs.image, hs.azimuth_deg, ps, msg)
        self.btn_png.setEnabled(True)
        shadow = f" · {hs.shadow_fraction * 100:.0f}% in cast shadow" if (not hs.night and self.chk_shadow.isChecked()) else ""
        self.hs_caption.setText(
            f"Illustrative only: generic reference terrain ({Path(self.dtm_path.text()).name}, {relief:.0f} m relief); {out.note}. "
            f"Shown at {ps:.3g} m/px, {out.shape[1]}×{out.shape[0]} px. "
            f"lit with the computed Sun azimuth {hs.azimuth_deg:.1f}° and incidence {hs.incidence_deg:.1f}°. "
            f"It is not the Mercury surface at the imaged location. Flat-ground brightness = cos(i) = {hs.flat_level:.2f}{shadow}. "
            "Contrast is stretched; arrow = direction to the Sun, north up.")

    def _hs_failed(self, job_id: int, msg: str) -> None:
        if job_id != self._job:
            return
        self.hs_caption.setStyleSheet(f"color: {theme.DANGER};")
        self.hs_caption.setText(msg)

    def _save_png(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Save hillshade", "hillshade.png", "PNG (*.png)")
        if p:
            self.view.png(p)

    # ------------------------------------------------------------------ output
    def _rows(self) -> list[tuple[str, str, str]]:
        r = self.result
        if r is None:
            return []
        rows = [("Camera", r.camera, ""), ("UTC", r.utc, ""), ("ET", f"{r.et:.6f}", "s"), ("Season", r.season, ""),
                ("MTA", f"{r.mta_deg:.3f}", "deg"), ("MTP", "" if r.mtp is None else str(r.mtp), ""),
                ("STP", "" if r.stp is None else str(r.stp), "")]
        rows += [(cap, fmt(r), unit) for _k, cap, unit, fmt, _t in METRICS]
        return rows

    def _copy_all(self) -> None:
        rows = self._rows()
        if rows:
            copy_to_clipboard("\n".join(f"{a}\t{b}\t{c}" for a, b, c in rows))

    def _export(self) -> None:
        if self.result is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export results", f"geometry_{self.result.season}.csv", "CSV (*.csv);;JSON (*.json)")
        if not p:
            return
        if p.lower().endswith(".json"):
            Path(p).write_text(json.dumps(self.result.to_dict(), indent=2), encoding="utf-8")
        else:
            with open(p, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["quantity", "value", "unit"])
                w.writerows(self._rows())
