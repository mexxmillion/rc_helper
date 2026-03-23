"""
output_panel.py
---------------
Panel for selecting output folders (EXR, PNG) and the Maya .ma output path.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _FolderRow(QHBoxLayout):
    def __init__(self, placeholder: str, parent_widget: QWidget) -> None:
        super().__init__()
        self._parent = parent_widget
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self.addWidget(self._edit)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        self.addWidget(btn)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self._parent, "Select output folder",
                                              self._edit.text() or "")
        if d:
            self._edit.setText(d)

    @property
    def path(self) -> str:
        return self._edit.text().strip()

    @path.setter
    def path(self, value: str) -> None:
        self._edit.setText(value)


class _FileRow(QHBoxLayout):
    def __init__(self, placeholder: str, file_filter: str, parent_widget: QWidget) -> None:
        super().__init__()
        self._parent = parent_widget
        self._filter = file_filter
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self.addWidget(self._edit)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        self.addWidget(btn)

    def _browse(self) -> None:
        f, _ = QFileDialog.getSaveFileName(
            self._parent, "Select output file",
            self._edit.text() or "",
            self._filter
        )
        if f:
            self._edit.setText(f)

    @property
    def path(self) -> str:
        return self._edit.text().strip()

    @path.setter
    def path(self, value: str) -> None:
        self._edit.setText(value)


class OutputPanel(QGroupBox):
    """Output folder/file selectors for EXR, PNG, and Maya scene."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Output", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._exr_row = _FolderRow("EXR output folder (ACEScg)", self)
        form.addRow("EXR folder:", self._exr_row)

        self._png_row = _FolderRow("PNG output folder (sRGB display)", self)
        form.addRow("PNG folder:", self._png_row)

        self._maya_row = _FileRow(
            "Maya .ma output path",
            "Maya ASCII (*.ma);;All files (*)",
            self,
        )
        form.addRow("Maya .ma file:", self._maya_row)

        root.addLayout(form)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def exr_output_dir(self) -> str:
        return self._exr_row.path

    @property
    def png_output_dir(self) -> str:
        return self._png_row.path

    @property
    def maya_output_path(self) -> str:
        return self._maya_row.path

    def set_defaults_from_source(self, source_dir: str) -> None:
        """Auto-fill output paths alongside the source folder."""
        from pathlib import Path
        if not source_dir:
            return
        src = Path(source_dir)
        self._exr_row.path = str(src / "undistorted_exr")
        self._png_row.path = str(src / "undistorted_png")
        self._maya_row.path = str(src / "maya" / "cameras.ma")
