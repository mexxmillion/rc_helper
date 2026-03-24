#!/usr/bin/env python
"""
main.py — RC Helper entry point.

Usage (from the repo root, inside the conda VFX environment):
    python main.py
"""

import sys
from pathlib import Path

# Make the src/ package importable without installing
sys.path.insert(0, str(Path(__file__).parent / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from rc_helper.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RC Helper")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("VFX")

    # High-DPI pixmaps — attribute removed in Qt6, set only if it exists
    _hdpi = getattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps", None)
    if _hdpi is not None:
        app.setAttribute(_hdpi, True)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
