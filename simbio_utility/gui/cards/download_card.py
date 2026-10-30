from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from ...core import download as dl
from ...resources import example_out_dir
from ...core.errors import UtilityError
from ..widgets import Debouncer, Panel, label
from .base import Card


class _DownloadThread(QThread):
    progress = Signal(object)  # download.Progress
    finished_ok = Signal(object)  # download.Report
    failed = Signal(str)

    def __init__(self, plan: dl.DownloadPlan, host: str, overwrite: bool) -> None:
        super().__init__()
        self.plan, self.host, self.overwrite = plan, host, overwrite
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            rep = dl.download(self.plan, self.host, overwrite=self.overwrite, cancel=lambda: self._cancel,
                              progress=self.progress.emit)
            self.finished_ok.emit(rep)
        except UtilityError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never let a worker thread die silently
            self.failed.emit(f"Unexpected error: {exc}")


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class DownloadCard(Card):
    title = "Kernel Download"
    subtitle = "Fetch every kernel listed in the metakernel from the ESA SPICE server"
    glyph = "⇩"
    needs_kernels = False  # works on the metakernel file itself - the kernels are not there yet

    def build(self, root: QWidget) -> None:
        self.metakernel_path = lambda: ""  # wired by the main window (the metakernel bar)
        self.load_metakernel = lambda path: None  # wired by the main window
        self._thread: _DownloadThread | None = None
        self._plan: dl.DownloadPlan | None = None
        self._new_mk: Path | None = None
        self._t0 = 0.0

        outer = QHBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        # ---------------- inputs ----------------
        left = Panel("Source & destination")
        left.setFixedWidth(460)
        left.body.addWidget(label("Metakernel (top bar)", "muted"))
        self.mk_label = label("", "mono", wrap=True, selectable=True)
        left.body.addWidget(self.mk_label)
        self.mk_info = label("", "small", wrap=True)
        left.body.addWidget(self.mk_info)

        left.body.addSpacing(6)
        left.body.addWidget(label("Server host name", "muted"))
        hrow = QHBoxLayout()
        self.host = QLineEdit(str(self.config.get("dl_host", "") or dl.DEFAULT_HOST))
        self.host.setProperty("mono", True)
        self.host.setToolTip(f"Anonymous FTP server. Default: {dl.DEFAULT_HOST}\n"
                             "Another host can be typed (optionally host:port); clear the field to restore the default.")
        self.btn_test = QPushButton("Test")
        self.btn_test.setToolTip("Connect anonymously and report the server greeting")
        hrow.addWidget(self.host, 1)
        hrow.addWidget(self.btn_test)
        left.body.addLayout(hrow)

        left.body.addWidget(label("Remote kernels path", "muted"))
        self.remote = QLineEdit(str(self.config.get("dl_remote_root", "") or dl.DEFAULT_REMOTE_ROOT))
        self.remote.setProperty("mono", True)
        self.remote.setToolTip("Folder on the server that holds the kernels (the $KERNELS of the metakernel). It is reproduced "
                               "below the output folder, so the downloaded tree keeps the ESA layout.")
        left.body.addWidget(self.remote)

        left.body.addWidget(label("Output folder", "muted"))
        orow = QHBoxLayout()
        self.out = QLineEdit(str(self.config.get("dl_out_dir", "")))
        self.out.setProperty("mono", True)
        self.out.setPlaceholderText(example_out_dir())
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.setStyleSheet("padding: 8px 0;")
        orow.addWidget(self.out, 1)
        orow.addWidget(bb)
        left.body.addLayout(orow)
        self.layout_hint = label("", "small", wrap=True, selectable=True)
        left.body.addWidget(self.layout_hint)

        self.chk_over = QCheckBox("Re-download files that already exist")
        self.chk_over.setToolTip("OFF (default): files already on disk with the same size as on the server are skipped.")
        left.body.addWidget(self.chk_over)

        left.body.addSpacing(8)
        self.btn = QPushButton("Download kernels")
        self.btn.setProperty("primary", True)
        left.body.addWidget(self.btn)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        left.body.addWidget(self.btn_cancel)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        left.body.addWidget(self.error)
        left.body.addStretch(1)
        outer.addWidget(left)

        # ---------------- progress ----------------
        right = Panel("Progress")
        self.status = label("Idle", "valuebig")
        right.body.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        right.body.addWidget(self.bar)
        self.current = label("", "mono", wrap=True)
        right.body.addWidget(self.current)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setProperty("mono", True)
        right.body.addWidget(self.log, 1)
        arow = QHBoxLayout()
        self.btn_load = QPushButton("Load the downloaded metakernel")
        self.btn_load.setProperty("primary", True)
        self.btn_load.setEnabled(False)
        self.btn_open = QPushButton("Open output folder")
        self.btn_open.setEnabled(False)
        arow.addWidget(self.btn_load)
        arow.addWidget(self.btn_open)
        arow.addStretch(1)
        right.body.addLayout(arow)
        outer.addWidget(right, 1)

        # ---------------- wiring ----------------
        self._refresh_deb = Debouncer(self.refresh, 250)
        self.out.textChanged.connect(self._refresh_deb)
        self.remote.textChanged.connect(self._refresh_deb)
        self.host.editingFinished.connect(self._host_edited)
        self.remote.editingFinished.connect(self._remote_edited)
        self.out.editingFinished.connect(lambda: self.config.set("dl_out_dir", self.out.text().strip()))
        bb.clicked.connect(self._browse)
        self.btn_test.clicked.connect(self._test)
        self.btn.clicked.connect(self.start)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_load.clicked.connect(self._load_new)
        self.btn_open.clicked.connect(self._open_folder)
        self.refresh()

    # ------------------------------------------------------------------ inputs
    def _host_edited(self) -> None:
        if not self.host.text().strip():
            self.host.setText(dl.DEFAULT_HOST)
        self.config.set("dl_host", "" if self.host.text().strip() == dl.DEFAULT_HOST else self.host.text().strip())

    def _remote_edited(self) -> None:
        if not self.remote.text().strip():
            self.remote.setText(dl.DEFAULT_REMOTE_ROOT)
        self.config.set("dl_remote_root", "" if self.remote.text().strip() == dl.DEFAULT_REMOTE_ROOT else self.remote.text().strip())

    def _browse(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "Output folder", self.out.text().strip() or "")
        if p:
            self.out.setText(p)
            self.config.set("dl_out_dir", p)

    def refresh(self) -> None:
        """Re-read the metakernel from the top bar and update the summary (cheap; called on every relevant change)."""
        path = (self.metakernel_path() or "").strip().strip('"')
        self.mk_label.setText(path or "— choose a metakernel in the bar above —")
        self._plan = None
        self.layout_hint.setText("")
        if not path:
            self.mk_info.setText("")
            return
        try:
            plan = dl.make_plan(path, self.out.text().strip() or ".", self.remote.text().strip() or dl.DEFAULT_REMOTE_ROOT)
        except UtilityError as exc:
            self.mk_info.setText(str(exc).splitlines()[0])
            return
        mk = plan.metakernel
        by = " · ".join(f"{k} {n}" for k, n in mk.counts_by_folder().items())
        txt = f"{len(mk.entries)} kernels  ({by})"
        if self.out.text().strip():
            txt += f" — {plan.present()} already in the output folder"
            self.layout_hint.setText(f"Files go to {plan.kernels_dir.as_posix()}/…\nA copy of the metakernel with the new PATH_VALUES "
                                     f"is written to …/mk/{mk.path.name}")
        if mk.skipped:
            txt += f"\n{len(mk.skipped)} entr{'y' if len(mk.skipped) == 1 else 'ies'} without a $SYMBOL path will be ignored"
        self.mk_info.setText(txt)

    # ------------------------------------------------------------------ actions
    def _show_error(self, msg: str) -> None:
        self.error.setText(msg)
        self.error.setVisible(bool(msg))

    def _test(self) -> None:
        self._show_error("")
        self.btn_test.setEnabled(False)
        try:
            self.status.setText("Testing connection…")
            self.repaint()
            greeting = dl.check_connection(self.host.text())
            self.status.setText("Server reachable")
            self._log(f"✓ {self.host.text().strip()}: {greeting}")
        except UtilityError as exc:
            self.status.setText("Server not reachable")
            self._show_error(str(exc))
        finally:
            self.btn_test.setEnabled(True)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._show_error("")
        try:
            dl.split_host(self.host.text())
            plan = dl.make_plan(self.metakernel_path(), self.out.text(), self.remote.text())
        except UtilityError as exc:
            self._show_error(str(exc))
            return
        self.config.set("dl_out_dir", self.out.text().strip())
        self._plan, self._new_mk = plan, None
        self.log.clear()
        self.bar.setValue(0)
        self.btn_load.setEnabled(False)
        self.btn_open.setEnabled(False)
        self._set_busy(True)
        self.status.setText("Connecting…")
        self._log(f"{plan.metakernel.path.name}: {len(plan.metakernel.entries)} kernels → {plan.kernels_dir.as_posix()}")
        for s in plan.metakernel.skipped:
            self._log(f"  ignored (no $SYMBOL path): {s}")
        self._t0 = time.time()
        self._thread = _DownloadThread(plan, self.host.text(), self.chk_over.isChecked())
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _cancel(self) -> None:
        if self._thread is not None:
            self._thread.cancel()
            self.btn_cancel.setEnabled(False)
            self.status.setText("Cancelling…")

    def _set_busy(self, busy: bool) -> None:
        for w in (self.btn, self.btn_test, self.host, self.remote, self.out, self.chk_over):
            w.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _thread_finished(self) -> None:
        self._thread = None
        self._set_busy(False)
        self.refresh()

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _on_progress(self, p: dl.Progress) -> None:
        frac = (p.index - 1 + (p.done / p.size if p.size else 0.0)) / max(1, p.total)
        if p.status in ("done", "exists", "failed"):
            frac = p.index / max(1, p.total)
        self.bar.setValue(int(1000 * min(1.0, frac)))
        if p.status == "start":
            self.status.setText(f"Downloading {p.index} / {p.total}")
            self._log(f"[{p.index}/{p.total}] {p.name}  ({_fmt_bytes(p.size)})" if p.size else f"[{p.index}/{p.total}] {p.name}")
        elif p.status == "bytes":
            self.current.setText(f"{p.name}\n{_fmt_bytes(p.done)} / {_fmt_bytes(p.size)}" if p.size else f"{p.name}\n{_fmt_bytes(p.done)}")
        elif p.status == "done":
            self.current.setText("")
        elif p.status == "exists":
            self.status.setText(f"Checking {p.index} / {p.total}")
            self._log(f"[{p.index}/{p.total}] {p.name}  — already present")
        elif p.status == "failed":
            self._log(f"[{p.index}/{p.total}] {p.name}  ✗ {p.message}")

    def _on_done(self, rep: dl.Report) -> None:
        self.current.setText("")
        self._log("")
        self._log(rep.summary())
        for name, err in rep.failed:
            self._log(f"  ✗ {name}: {err}")
        if rep.cancelled:
            self.status.setText("Cancelled")
        elif rep.failed:
            self.status.setText(f"Done with {len(rep.failed)} error(s)")
            self._show_error(f"{len(rep.failed)} kernel(s) could not be downloaded - see the log. "
                             "Run again to retry only the missing ones.")
        else:
            self.bar.setValue(1000)
            self.status.setText("Download complete")
        if rep.metakernel:
            self._new_mk = rep.metakernel
            self._log(f"metakernel written: {rep.metakernel}")
            self.btn_load.setEnabled(True)
        if self._plan:
            self.btn_open.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self.status.setText("Failed")
        self.current.setText("")
        self._show_error(msg)
        self._log("✗ " + msg.splitlines()[0])

    def _load_new(self) -> None:
        if self._new_mk:
            self.load_metakernel(str(self._new_mk))

    def _open_folder(self) -> None:
        if self._plan:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._plan.kernels_dir)))

    def shutdown(self) -> None:
        if self._thread is not None:
            self._thread.cancel()
            self._thread.wait(5000)
