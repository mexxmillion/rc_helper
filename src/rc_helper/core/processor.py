"""
processor.py
------------
Orchestration pipeline that ties together file matching, image processing,
and Maya export.  Designed to run inside a QThread so the UI stays responsive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .file_matcher import MatchedSet, find_matched_sets
from .oiio_processor import process_image
from .xmp_parser import CameraData, parse_xmp
from .maya_exporter import write_maya_scene

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int], None]   # (current, total)
AbortFn = Callable[[], bool]              # returns True when abort is requested


@dataclass
class ProcessSettings:
    """All user-configurable options for a processing run."""

    # ── Folders ──────────────────────────────────────────────────────────
    source_dir: str = ""
    stmap_dir: str = ""           # empty → auto-detect <source_dir>/stmaps
    exr_output_dir: str = ""      # empty → skip EXR output
    png_output_dir: str = ""      # empty → skip PNG output
    maya_output_path: str = ""    # empty → skip Maya export

    # ── Color management ─────────────────────────────────────────────────
    source_cs: str = "sRGB"
    acescg_cs: str = "ACES - ACEScg"
    srgb_display_cs: str = "Output - sRGB"
    ocio_config: str = ""         # empty → use $OCIO env var

    # ── Operation toggles ────────────────────────────────────────────────
    do_undistort: bool = True
    do_png: bool = True           # write sRGB PNG output
    do_maya_export: bool = True

    # ── Tool overrides ───────────────────────────────────────────────────
    oiiotool_path: str = ""       # empty → find oiiotool on PATH

    # ── Derived helpers ───────────────────────────────────────────────────
    @property
    def exr_dir(self) -> Optional[Path]:
        return Path(self.exr_output_dir) if self.exr_output_dir else None

    @property
    def png_dir(self) -> Optional[Path]:
        return Path(self.png_output_dir) if self.png_output_dir else None

    @property
    def maya_path(self) -> Optional[Path]:
        return Path(self.maya_output_path) if self.maya_output_path else None

    @property
    def stmap_folder(self) -> Optional[str]:
        return self.stmap_dir if self.stmap_dir else None


def run(
    settings: ProcessSettings,
    progress_fn: Optional[ProgressFn] = None,
    log_fn: Optional[LogFn] = None,
    abort_fn: Optional[AbortFn] = None,
) -> dict:
    """
    Execute the full processing pipeline.

    Returns a summary dict with keys:
      processed, skipped, errors, maya_file
    """
    log = log_fn or (lambda s: None)
    progress = progress_fn or (lambda cur, tot: None)
    is_aborted = abort_fn or (lambda: False)

    # ── 1. Match files ────────────────────────────────────────────────────
    log("Scanning source directory…")
    matched_sets = find_matched_sets(settings.source_dir, settings.stmap_folder)

    total = len(matched_sets)
    n_stmap = sum(1 for m in matched_sets if m.has_stmap)
    n_xmp   = sum(1 for m in matched_sets if m.has_xmp)
    n_raw   = sum(1 for m in matched_sets if m.is_raw)

    log(f"Found {total} source images  ({n_raw} raw  |  {n_stmap} ST maps  |  {n_xmp} XMP)")

    if n_stmap == 0 and settings.do_undistort:
        log("  NOTE: no ST maps found — undistortion will be skipped for all images.")
    if n_xmp == 0 and settings.do_maya_export:
        log("  NOTE: no XMP sidecars found — Maya export will be skipped.")

    if total == 0:
        return {"processed": 0, "skipped": 0, "errors": 0, "maya_file": None}

    # ── 2. Process images ─────────────────────────────────────────────────
    cameras: list[CameraData] = []
    png_paths: dict[str, Optional[Path]] = {}
    processed = skipped = errors = 0

    for idx, ms in enumerate(matched_sets):
        if is_aborted():
            log("\nAbort requested — stopping after current image.")
            break
        progress(idx, total)
        log(f"\n[{idx + 1}/{total}] {ms.source.name}")

        try:
            result = process_image(
                ms,
                source_cs=settings.source_cs,
                exr_output_dir=settings.exr_dir,
                png_output_dir=settings.png_dir if settings.do_png else None,
                acescg_cs=settings.acescg_cs,
                srgb_display_cs=settings.srgb_display_cs,
                ocio_config=settings.ocio_config or None,
                do_undistort=settings.do_undistort,
                oiiotool_override=settings.oiiotool_path or None,
                log=log,
            )
            png_paths[ms.stem] = result.get("png")
            processed += 1
        except Exception as exc:
            log(f"  ERROR: {exc}")
            errors += 1
            png_paths[ms.stem] = None

        # Parse XMP if present (needed for Maya export)
        if settings.do_maya_export and ms.has_xmp:
            try:
                cam = parse_xmp(ms.xmp)
                cameras.append(cam)
            except Exception as exc:
                log(f"  XMP parse error: {exc}")

    progress(total, total)

    # ── 3. Maya export ────────────────────────────────────────────────────
    # Resolve PNG paths for image planes.
    # Priority: path that was just written > expected path from png_output_dir.
    # This ensures image planes are populated even when:
    #   - "Export PNG" toggle is off but the dir is still set
    #   - image processing failed for some files
    #   - PNGs were produced in a previous run
    maya_png_paths: dict[str, Optional[Path]] = dict(png_paths)
    if settings.png_output_dir:
        png_fallback_dir = Path(settings.png_output_dir)
        for ms in matched_sets:
            if not maya_png_paths.get(ms.stem):
                maya_png_paths[ms.stem] = png_fallback_dir / (ms.stem + ".png")

    maya_file: Optional[Path] = None
    if settings.do_maya_export and settings.maya_path:
        if not cameras:
            log("\nMaya export skipped — no XMP data was parsed (no .xmp sidecars found).")
        else:
            log(f"\nWriting Maya scene: {settings.maya_path}")
            try:
                maya_file = write_maya_scene(cameras, maya_png_paths, settings.maya_path)
                log(f"  Maya scene written: {maya_file}")
            except Exception as exc:
                log(f"  Maya export error: {exc}")
                errors += 1

    aborted = is_aborted()
    if aborted:
        log(f"Aborted — processed: {processed}, errors: {errors} (remaining images skipped)")
    else:
        log(f"\nDone — processed: {processed}, skipped: {skipped}, errors: {errors}")
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "maya_file": maya_file,
        "aborted": aborted,
    }
