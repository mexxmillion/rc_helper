"""
source_panel.py
---------------
Panel for selecting the source image folder and OCIO color space options.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import ocio_utils


class SourcePanel(QGroupBox):
    """Folder selector + color space dropdowns for source images."""

    source_dir_changed = Signal(str)
    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Source Images", parent)
        self._build_ui()
        self._connect()
        self._load_color_spaces()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Folder row
        folder_row = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("Select source image folder…")
        self._dir_edit.setReadOnly(True)
        folder_row.addWidget(self._dir_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        folder_row.addWidget(browse_btn)
        root.addLayout(folder_row)

        # OCIO config row
        ocio_row = QHBoxLayout()
        self._ocio_edit = QLineEdit()
        self._ocio_edit.setPlaceholderText("OCIO config (leave blank for $OCIO env var)")
        ocio_row.addWidget(self._ocio_edit)
        ocio_browse = QPushButton("Browse…")
        ocio_browse.clicked.connect(self._browse_ocio)
        ocio_row.addWidget(ocio_browse)
        root.addLayout(ocio_row)

        # Color space form
        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)

        self._source_cs_combo = QComboBox()
        self._source_cs_combo.setMinimumWidth(260)
        self._source_cs_combo.setToolTip(
            "Input color space for LDR images (JPG/PNG/TIFF).\n"
            "Camera raw files are always converted to scene-linear first."
        )
        form.addRow("Source color space:", self._source_cs_combo)

        self._acescg_combo = QComboBox()
        self._acescg_combo.setToolTip("Destination color space for EXR output.")
        form.addRow("EXR target (ACEScg):", self._acescg_combo)

        self._srgb_combo = QComboBox()
        self._srgb_combo.setToolTip("Destination color space for PNG output.")
        form.addRow("PNG target (sRGB display):", self._srgb_combo)

        root.addLayout(form)

        # oiiotool override row (toggle + path browser)
        oiio_row = QHBoxLayout()
        self._oiio_override_chk = QCheckBox("Custom oiiotool:")
        self._oiio_override_chk.setToolTip(
            "When checked, use the specified oiiotool binary instead of the one on PATH."
        )
        self._oiio_override_chk.setFixedWidth(140)
        oiio_row.addWidget(self._oiio_override_chk)
        self._oiio_edit = QLineEdit()
        self._oiio_edit.setPlaceholderText("Path to oiiotool binary (leave unchecked for PATH)")
        self._oiio_edit.setEnabled(False)
        oiio_row.addWidget(self._oiio_edit)
        self._oiio_browse_btn = QPushButton("Browse…")
        self._oiio_browse_btn.setEnabled(False)
        self._oiio_browse_btn.clicked.connect(self._browse_oiiotool)
        oiio_row.addWidget(self._oiio_browse_btn)
        root.addLayout(oiio_row)
        self._oiio_override_chk.toggled.connect(self._oiio_edit.setEnabled)
        self._oiio_override_chk.toggled.connect(self._oiio_browse_btn.setEnabled)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        root.addWidget(self._status_label)

    def _connect(self) -> None:
        self._ocio_edit.editingFinished.connect(self._load_color_spaces)
        self._source_cs_combo.currentIndexChanged.connect(self.settings_changed)
        self._acescg_combo.currentIndexChanged.connect(self.settings_changed)
        self._srgb_combo.currentIndexChanged.connect(self.settings_changed)

    # ── Color space loading ───────────────────────────────────────────────

    def _load_color_spaces(self) -> None:
        config_path = self._ocio_edit.text().strip() or None
        try:
            spaces = ocio_utils.get_color_spaces(config_path)
            source = self.source_cs  # preserve selection
            acescg = self.acescg_cs
            srgb = self.srgb_display_cs

            for combo in (self._source_cs_combo, self._acescg_combo, self._srgb_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(spaces)
                combo.blockSignals(False)

            self._set_combo_to(self._source_cs_combo, source or ocio_utils.default_ldr_source(config_path))
            self._set_combo_to(self._acescg_combo, acescg or ocio_utils.default_acescg(config_path))
            self._set_combo_to(self._srgb_combo, srgb or ocio_utils.default_display_srgb(config_path))

            src = "custom config" if config_path else ("$OCIO" if os.environ.get("OCIO") else "built-in")
            self._status_label.setText(f"{len(spaces)} color spaces loaded ({src})")
        except Exception as exc:
            self._status_label.setStyleSheet("color: #ff7b8a; font-size: 11px;")
            self._status_label.setText(f"OCIO error: {exc}")

    @staticmethod
    def _set_combo_to(combo: QComboBox, name: str) -> None:
        idx = combo.findText(name)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif combo.count():
            combo.setCurrentIndex(0)

    # ── Slots ─────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select source image folder",
                                              self._dir_edit.text() or "")
        if d:
            self._dir_edit.setText(d)
            self.source_dir_changed.emit(d)

    def _browse_ocio(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Select OCIO config", "",
            "OCIO config (*.ocio);;All files (*)"
        )
        if f:
            self._ocio_edit.setText(f)
            self._load_color_spaces()

    def _browse_oiiotool(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Select oiiotool binary",
            self._oiio_edit.text() or "",
            "Executable (*.exe);;All files (*)"
        )
        if f:
            self._oiio_edit.setText(f)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def source_dir(self) -> str:
        return self._dir_edit.text().strip()

    @property
    def ocio_config(self) -> str:
        return self._ocio_edit.text().strip()

    @property
    def source_cs(self) -> str:
        return self._source_cs_combo.currentText()

    @property
    def acescg_cs(self) -> str:
        return self._acescg_combo.currentText()

    @property
    def srgb_display_cs(self) -> str:
        return self._srgb_combo.currentText()

    @property
    def oiiotool_path(self) -> str:
        """Custom oiiotool path, or empty string if using PATH."""
        if self._oiio_override_chk.isChecked():
            return self._oiio_edit.text().strip()
        return ""
