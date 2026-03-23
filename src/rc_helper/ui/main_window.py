"""
main_window.py
--------------
Main application window.

Layout
------
  ┌──────────────────────────────────────────────────────────┐
  │  Source Images panel                                     │
  ├──────────────────────────────────────────────────────────┤
  │  ST Maps panel                                           │
  ├──────────────────────────────────────────────────────────┤
  │  Output panel                                            │
  ├──────────────────────────────────────────────────────────┤
  │  Log / console (scrollable)                              │
  ├──────────────────────────────────────────────────────────┤
  │  Process panel (toggles + progress + button)             │
  └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .source_panel import SourcePanel
from .stmap_panel import StmapPanel
from .output_panel import OutputPanel
from .process_panel import ProcessPanel
from .stylesheet import APP_STYLESHEET
from ..core.processor import ProcessSettings


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RC Helper — RealityCapture Data Processor")
        self.resize(960, 1000)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._connect()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Top panels ────────────────────────────────────────────────────
        self._source_panel = SourcePanel()
        layout.addWidget(self._source_panel)

        self._stmap_panel = StmapPanel()
        layout.addWidget(self._stmap_panel, stretch=3)

        self._output_panel = OutputPanel()
        layout.addWidget(self._output_panel)

        # ── Log ───────────────────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        mono = QFont("Consolas", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._log.setFont(mono)
        self._log.setPlaceholderText("Processing log will appear here…")
        self._log.setMinimumHeight(120)
        layout.addWidget(self._log, stretch=1)

        # ── Process panel ─────────────────────────────────────────────────
        self._process_panel = ProcessPanel()
        layout.addWidget(self._process_panel)

    def _connect(self) -> None:
        self._source_panel.source_dir_changed.connect(self._on_source_dir_changed)
        self._process_panel.process_requested.connect(self._on_process)

        # Forward worker log messages to the log widget
        # (connected dynamically when worker is created — see _on_process)

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_source_dir_changed(self, path: str) -> None:
        self._stmap_panel.set_source_dir(path)
        self._output_panel.set_defaults_from_source(path)

    def _on_process(self) -> None:
        if not self._validate():
            return

        settings = self._build_settings()
        self._log.clear()

        proc_panel = self._process_panel
        # start_processing creates the worker; connect log signal immediately after
        proc_panel.start_processing(settings)
        proc_panel._worker.log_message.connect(self._append_log)

    def _validate(self) -> bool:
        source = self._source_panel.source_dir
        if not source:
            QMessageBox.warning(self, "Missing input", "Please select a source image folder.")
            return False

        do_exr = self._process_panel.do_exr
        do_png = self._process_panel.do_png
        do_maya = self._process_panel.do_maya

        if do_exr and not self._output_panel.exr_output_dir:
            QMessageBox.warning(self, "Missing output", "Please set an EXR output folder.")
            return False
        if do_png and not self._output_panel.png_output_dir:
            QMessageBox.warning(self, "Missing output", "Please set a PNG output folder.")
            return False
        if do_maya and not self._output_panel.maya_output_path:
            QMessageBox.warning(self, "Missing output", "Please set a Maya .ma output path.")
            return False

        return True

    def _build_settings(self) -> ProcessSettings:
        s = ProcessSettings()
        s.source_dir = self._source_panel.source_dir
        s.stmap_dir = self._stmap_panel.stmap_dir
        s.source_cs = self._source_panel.source_cs
        s.acescg_cs = self._source_panel.acescg_cs
        s.srgb_display_cs = self._source_panel.srgb_display_cs
        s.ocio_config = self._source_panel.ocio_config

        s.exr_output_dir = self._output_panel.exr_output_dir if self._process_panel.do_exr else ""
        # Always pass png_output_dir so the Maya exporter can reference PNG paths
        # even when "Export PNG" is toggled off (e.g. PNGs from a previous run).
        s.png_output_dir = self._output_panel.png_output_dir
        s.do_png = self._process_panel.do_png
        s.maya_output_path = self._output_panel.maya_output_path if self._process_panel.do_maya else ""

        s.do_undistort = self._process_panel.do_undistort
        s.do_maya_export = self._process_panel.do_maya
        s.oiiotool_path = self._source_panel.oiiotool_path

        return s

    def _append_log(self, msg: str) -> None:
        self._log.appendPlainText(msg)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )
