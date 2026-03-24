"""
process_panel.py
----------------
Bottom bar with operation toggles, progress bar, and the Process button.
Also contains the ProcessWorker QThread that runs the pipeline off the UI thread.
"""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.processor import ProcessSettings, run as core_run


class ProcessWorker(QThread):
    """Runs the processing pipeline on a background thread."""

    log_message = Signal(str)
    progress_updated = Signal(int, int)   # (current, total)
    finished_with_result = Signal(dict)

    def __init__(self, settings: ProcessSettings) -> None:
        super().__init__()
        self._settings = settings
        self._abort = False

    def abort(self) -> None:
        """Signal the worker to stop after the current image finishes."""
        self._abort = True

    def run(self) -> None:
        result = core_run(
            self._settings,
            progress_fn=lambda cur, tot: self.progress_updated.emit(cur, tot),
            log_fn=lambda msg: self.log_message.emit(msg),
            abort_fn=lambda: self._abort,
        )
        self.finished_with_result.emit(result)


class ProcessPanel(QGroupBox):
    """Toggles + progress + process button."""

    process_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Process", parent)
        self._worker: ProcessWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Toggle rows ───────────────────────────────────────────────────
        # Row 1: image processing operations
        img_row = QHBoxLayout()

        self._undistort_cb = QCheckBox("Undistort  (ST map warp)")
        self._undistort_cb.setChecked(True)
        self._undistort_cb.setToolTip(
            "Apply oiiotool --st_warp using the matched ST map.\n"
            "Automatically skipped if no ST map is found for an image."
        )
        img_row.addWidget(self._undistort_cb)

        self._exr_cb = QCheckBox("Export EXR  (ACEScg)")
        self._exr_cb.setChecked(True)
        self._exr_cb.setToolTip("Write ACEScg linear EXR to the EXR output folder.")
        img_row.addWidget(self._exr_cb)

        self._png_cb = QCheckBox("Export PNG  (sRGB display)")
        self._png_cb.setChecked(True)
        self._png_cb.setToolTip("Write sRGB display PNG to the PNG output folder.")
        img_row.addWidget(self._png_cb)

        img_row.addStretch()
        root.addLayout(img_row)

        # Row 2: Maya export (separate since it needs XMP)
        maya_row = QHBoxLayout()

        self._maya_cb = QCheckBox("Generate Maya scene  (requires XMP sidecars)")
        self._maya_cb.setChecked(True)
        self._maya_cb.setToolTip(
            "Parse RC .xmp sidecars and write a Maya ASCII .ma with cameras\n"
            "and image planes linked to the undistorted PNGs.\n"
            "Automatically skipped if no XMP files are found."
        )
        maya_row.addWidget(self._maya_cb)

        maya_row.addStretch()
        root.addLayout(maya_row)

        # ── Progress + button row ─────────────────────────────────────────
        action_row = QHBoxLayout()

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m  (%p%)")
        action_row.addWidget(self._progress, stretch=1)

        self._process_btn = QPushButton("Process")
        self._process_btn.setFixedWidth(110)
        self._process_btn.setDefault(True)
        self._process_btn.setProperty("variant", "primary")
        self._process_btn.clicked.connect(self.process_requested)
        action_row.addWidget(self._process_btn)

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.setFixedWidth(90)
        self._abort_btn.setEnabled(False)
        self._abort_btn.setToolTip("Stop after the current image finishes")
        self._abort_btn.setProperty("variant", "danger")
        self._abort_btn.clicked.connect(self._on_abort_clicked)
        action_row.addWidget(self._abort_btn)

        root.addLayout(action_row)

        # Status label
        self._status_label = QLabel("Ready.")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._status_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        root.addWidget(self._status_label)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def do_undistort(self) -> bool:
        return self._undistort_cb.isChecked()

    @property
    def do_exr(self) -> bool:
        return self._exr_cb.isChecked()

    @property
    def do_png(self) -> bool:
        return self._png_cb.isChecked()

    @property
    def do_maya(self) -> bool:
        return self._maya_cb.isChecked()

    def start_processing(self, settings: ProcessSettings) -> None:
        if self._worker and self._worker.isRunning():
            return

        self._process_btn.setEnabled(False)
        self._process_btn.setText("Running…")
        self._abort_btn.setEnabled(True)
        self._progress.setValue(0)
        self._status_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        self._status_label.setText("Processing…")

        self._worker = ProcessWorker(settings)
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.start()

    def _on_abort_clicked(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._abort_btn.setEnabled(False)
            self._abort_btn.setText("Aborting…")
            self._status_label.setStyleSheet("color: #e3a03a; font-size: 11px;")
            self._status_label.setText("Aborting — finishing current image…")

    def _on_progress(self, current: int, total: int) -> None:
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(current)

    def _on_finished(self, result: dict) -> None:
        self._process_btn.setEnabled(True)
        self._process_btn.setText("Process")
        self._abort_btn.setEnabled(False)
        self._abort_btn.setText("Abort")

        aborted = result.get("aborted", False)
        errs = result.get("errors", 0)
        done = result.get("processed", 0)
        maya = result.get("maya_file")
        error_details = result.get("error_details", [])

        if aborted:
            self._progress.setMaximum(100)
            self._progress.setValue(0)
            msg = f"Aborted — {done} processed"
            if errs:
                msg += f", {errs} errors"
            self._status_label.setStyleSheet("color: #e3a03a; font-size: 11px;")
        else:
            self._progress.setMaximum(100)
            self._progress.setValue(100)
            msg = f"Done — {done} processed"
            if errs:
                # Show which files failed in the status line
                failed_names = [name for name, _ in error_details[:3]]
                msg += f", {errs} error(s): {', '.join(failed_names)}"
                if errs > 3:
                    msg += f" +{errs - 3} more"
                msg += "  (see log for details)"
                self._status_label.setStyleSheet("color: #ff7b8a; font-size: 11px;")
            else:
                self._status_label.setStyleSheet("color: #3fb950; font-size: 11px;")

        if maya:
            msg += f" | Maya: {Path(str(maya)).name}"
        self._status_label.setText(msg)
