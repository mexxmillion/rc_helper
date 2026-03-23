"""
stmap_panel.py
--------------
Panel for selecting the ST map folder and previewing matched pairs.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.file_matcher import MatchedSet, find_matched_sets


class StmapPanel(QGroupBox):
    """Folder selector for ST maps and a matched-pairs preview list."""

    stmap_dir_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ST Maps", parent)
        self._source_dir: str = ""
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Folder row
        folder_row = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText(
            "ST maps folder (leave blank to auto-detect <source>/stmaps/)"
        )
        self._dir_edit.setReadOnly(True)
        folder_row.addWidget(self._dir_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        folder_row.addWidget(browse_btn)
        clear_btn = QPushButton("Auto")
        clear_btn.setFixedWidth(44)
        clear_btn.setToolTip("Clear path — use auto-detected stmaps/ subfolder")
        clear_btn.clicked.connect(self._clear)
        folder_row.addWidget(clear_btn)
        root.addLayout(folder_row)

        # Summary label
        self._summary_label = QLabel("No source folder selected.")
        self._summary_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        root.addWidget(self._summary_label)

        # Pair list — let it fill available vertical space
        self._pair_list = QListWidget()
        self._pair_list.setMinimumHeight(260)
        self._pair_list.setAlternatingRowColors(True)
        self._pair_list.setUniformItemSizes(True)
        root.addWidget(self._pair_list, stretch=1)

    # ── Slots ─────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select ST maps folder",
                                              self._dir_edit.text() or "")
        if d:
            self._dir_edit.setText(d)
            self.stmap_dir_changed.emit(d)
            self._refresh_pairs()

    def _clear(self) -> None:
        self._dir_edit.setText("")
        self.stmap_dir_changed.emit("")
        self._refresh_pairs()

    # ── Public API ────────────────────────────────────────────────────────

    def set_source_dir(self, source_dir: str) -> None:
        """Called by main window when the source folder changes."""
        self._source_dir = source_dir
        self._refresh_pairs()

    @property
    def stmap_dir(self) -> str:
        return self._dir_edit.text().strip()

    # ── Internals ─────────────────────────────────────────────────────────

    def _refresh_pairs(self) -> None:
        self._pair_list.clear()
        if not self._source_dir:
            self._summary_label.setText("No source folder selected.")
            return

        stmap_dir = self.stmap_dir or None
        try:
            sets: list[MatchedSet] = find_matched_sets(self._source_dir, stmap_dir)
        except FileNotFoundError as exc:
            self._summary_label.setText(f"Error: {exc}")
            return

        with_stmap = sum(1 for s in sets if s.has_stmap)
        without_stmap = len(sets) - with_stmap
        with_xmp = sum(1 for s in sets if s.has_xmp)

        summary = f"{len(sets)} images | {with_stmap} with ST map | {with_xmp} with XMP"
        if without_stmap:
            summary += f"  —  {without_stmap} missing ST map (undistortion will be skipped for those)"
            self._summary_label.setStyleSheet("color: #e3a03a; font-size: 11px;")
        else:
            self._summary_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        self._summary_label.setText(summary)

        for ms in sets:
            stmap_flag = "✓ stmap" if ms.has_stmap else "✗ stmap"
            xmp_flag = "✓ xmp" if ms.has_xmp else "✗ xmp"
            item = QListWidgetItem(f"{ms.source.name}  [{stmap_flag}]  [{xmp_flag}]")
            if not ms.has_stmap:
                item.setForeground(Qt.GlobalColor.darkYellow)
            self._pair_list.addItem(item)
