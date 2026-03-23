"""
file_matcher.py
---------------
Pairs source images with their ST maps and XMP sidecars.

ST map naming convention from RealityCapture:
    <stem>.jpg  →  stmaps/<stem>.jpg.stmap.exr
    <stem>.png  →  stmaps/<stem>.png.stmap.exr
    etc.

XMP sidecar convention (RC exports them alongside the source image):
    <stem>.jpg  →  <stem>.xmp
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Extensions treated as source images
RAW_EXTENSIONS = {".cr2", ".cr3", ".arw", ".nef", ".nrw", ".raf",
                  ".orf", ".rw2", ".dng", ".raw", ".3fr", ".mef",
                  ".mrw", ".pef", ".srw", ".x3f"}

LDR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
HDR_EXTENSIONS = {".exr", ".hdr", ".dpx"}

SOURCE_EXTENSIONS = LDR_EXTENSIONS | HDR_EXTENSIONS | RAW_EXTENSIONS


@dataclass
class MatchedSet:
    """One logical capture: source image + optional ST map + optional XMP."""
    source: Path
    stmap: Optional[Path] = None
    xmp: Optional[Path] = None

    @property
    def stem(self) -> str:
        """Original filename stem, e.g. '1_YukihiroIwayama'."""
        return self.source.stem

    @property
    def is_raw(self) -> bool:
        return self.source.suffix.lower() in RAW_EXTENSIONS

    @property
    def is_ldr(self) -> bool:
        return self.source.suffix.lower() in LDR_EXTENSIONS

    @property
    def is_hdr(self) -> bool:
        return self.source.suffix.lower() in HDR_EXTENSIONS

    @property
    def has_stmap(self) -> bool:
        return self.stmap is not None and self.stmap.exists()

    @property
    def has_xmp(self) -> bool:
        return self.xmp is not None and self.xmp.exists()


def find_matched_sets(
    source_dir: str | Path,
    stmap_dir: Optional[str | Path] = None,
) -> list[MatchedSet]:
    """
    Scan *source_dir* for images, then try to find matching ST maps and XMPs.

    Parameters
    ----------
    source_dir:
        Folder containing source images (and XMP sidecars).
    stmap_dir:
        Folder containing ST map EXRs.  If None, defaults to
        ``<source_dir>/stmaps/``.

    Returns
    -------
    list[MatchedSet]
        Sorted by source filename.
    """
    source_dir = Path(source_dir)
    if stmap_dir is None:
        stmap_dir = source_dir / "stmaps"
    else:
        stmap_dir = Path(stmap_dir)

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    # Collect all source images
    sources: list[Path] = sorted(
        p for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS
    )

    # Build stmap lookup: "1_YukihiroIwayama.jpg" → Path(stmap.exr)
    stmap_lookup: dict[str, Path] = {}
    if stmap_dir.is_dir():
        for p in stmap_dir.iterdir():
            if p.is_file() and p.name.endswith(".stmap.exr"):
                # Strip ".stmap.exr" to recover original filename
                original_name = p.name[: -len(".stmap.exr")]
                stmap_lookup[original_name] = p

    matched: list[MatchedSet] = []
    for src in sources:
        stmap = stmap_lookup.get(src.name)
        xmp = src.with_suffix(".xmp")
        if not xmp.exists():
            xmp = None  # type: ignore[assignment]

        matched.append(MatchedSet(source=src, stmap=stmap, xmp=xmp))

    return matched


def summarise(sets: list[MatchedSet]) -> str:
    """Return a human-readable summary of matched sets."""
    total = len(sets)
    with_stmap = sum(1 for s in sets if s.has_stmap)
    with_xmp = sum(1 for s in sets if s.has_xmp)
    return (
        f"{total} source images | "
        f"{with_stmap} with ST maps | "
        f"{with_xmp} with XMP"
    )
