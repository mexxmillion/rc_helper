"""
stmap_panel.py
--------------
Panel for selecting the ST map folder and previewing matched pairs.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.file_matcher import MatchedSet, find_matched_sets

_COL_SOURCE = 0
_COL_STMAP  = 1
_COL_XMP    = 2


class StmapPanel(QGroupBox):
    """Folder selector for ST maps and a matched-pairs preview table."""

    stmap_dir_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ST Maps & File Pairs", parent)
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

        # Pair table
        self._pair_tree = QTreeWidget()
        self._pair_tree.setColumnCount(3)
        self._pair_tree.setHeaderLabels(["Source Image", "ST Map", "XMP"])
        self._pair_tree.setRootIsDecorated(False)
        self._pair_tree.setUniformRowHeights(True)
        self._pair_tree.setAlternatingRowColors(True)
        self._pair_tree.setSelectionMode(QAbstractItemView.NoSelection)
        self._pair_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pair_tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._pair_tree.setMinimumHeight(600)

        hdr = self._pair_tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        root.addWidget(self._pair_tree, stretch=1)

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
        self._pair_tree.clear()
        if not self._source_dir:
            self._summary_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
            self._summary_label.setText("No source folder selected.")
            return

        stmap_dir = self.stmap_dir or None
        try:
            sets: list[MatchedSet] = find_matched_sets(self._source_dir, stmap_dir)
        except FileNotFoundError as exc:
            self._summary_label.setStyleSheet("color: #ff7b8a; font-size: 11px;")
            self._summary_label.setText(f"Error: {exc}")
            return

        with_stmap = sum(1 for s in sets if s.has_stmap)
        without_stmap = len(sets) - with_stmap
        with_xmp = sum(1 for s in sets if s.has_xmp)

        summary = f"{len(sets)} images  |  {with_stmap} ST maps  |  {with_xmp} XMP"
        if without_stmap:
            summary += f"  —  {without_stmap} missing ST map (undistortion skipped)"
            self._summary_label.setStyleSheet("color: #e3a03a; font-size: 11px;")
        else:
            self._summary_label.setStyleSheet("color: #96a4b5; font-size: 11px;")
        self._summary_label.setText(summary)

        for ms in sets:
            stmap_text = ms.stmap.name if ms.has_stmap else "—"
            xmp_text   = ms.xmp.name  if ms.has_xmp   else "—"
            item = QTreeWidgetItem([ms.source.name, stmap_text, xmp_text])

            if not ms.has_stmap:
                # Amber tint for rows missing an ST map
                for col in range(3):
                    item.setForeground(col, Qt.GlobalColor.darkYellow)

            self._pair_tree.addTopLevelItem(item)
