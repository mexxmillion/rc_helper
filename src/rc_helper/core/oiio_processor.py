"""
oiio_processor.py
-----------------
Wraps oiiotool as a subprocess for all image processing operations.

Pipeline (correct order):
  1. Camera raw → scene-linear EXR          (libraw decode, temp file)
  2. OCIO colorconvert → ACEScg linear      (all pixel ops happen in linear)
  3. ST-map undistortion (--st_warp)        (interpolation in linear light)
  4. Write ACEScg EXR                       (image is already in working space)
  5. OCIO colorconvert ACEScg → sRGB display → PNG

Steps 2-5 are issued as a single chained oiiotool command so no extra
round-trips or temp files are needed after the optional raw decode.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .file_matcher import MatchedSet
from .ocio_utils import build_colorconvert_args

LogFn = Callable[[str], None]


def _find_oiiotool(override: Optional[str] = None) -> str:
    """
    Locate oiiotool.

    Priority:
      1. *override* path (if given and the file exists)
      2. ``oiiotool`` on PATH

    Raises FileNotFoundError if nothing is found.
    """
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        raise FileNotFoundError(f"oiiotool override not found: {override}")
    tool = shutil.which("oiiotool")
    if tool is None:
        raise FileNotFoundError(
            "oiiotool not found on PATH. "
            "Ensure OpenImageIO is installed in your conda VFX environment."
        )
    return tool


def _run(cmd: list[str], log: Optional[LogFn] = None) -> str:
    """Run *cmd*, stream output to *log*, and raise on non-zero exit."""
    log = log or (lambda s: None)
    log(f"$ {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.splitlines():
            log(f"  {line}")

    if result.returncode != 0:
        raise RuntimeError(
            f"oiiotool exited with code {result.returncode}. "
            f"Command: {' '.join(cmd)}"
        )
    return result.stdout or ""


def convert_raw_to_linear(
    src: Path,
    dst: Path,
    log: Optional[LogFn] = None,
    oiiotool_override: Optional[str] = None,
) -> Path:
    """
    Read a camera-raw file with oiiotool (via libraw) and write a linear EXR.
    oiiotool reads raw files natively when built with libraw support.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    oiio = _find_oiiotool(oiiotool_override)
    cmd = [oiio, str(src), "-o", str(dst)]
    _run(cmd, log)
    return dst


def undistort_with_stmap(
    src: Path,
    stmap: Path,
    dst: Path,
    log: Optional[LogFn] = None,
    oiiotool_override: Optional[str] = None,
) -> Path:
    """
    Apply an ST-map (UV remap) to *src* and write the result to *dst*.

    NOTE: *src* should already be in a linear colour space (ACEScg) so that
    bilinear interpolation during the warp is performed in linear light.

    flip_t=1 is required because RealityCapture ST maps use T=0 at the top
    (image/DCC convention) while oiiotool --st_warp expects T=0 at the bottom
    (OpenGL UV convention).  Without it the output is vertically flipped.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    oiio = _find_oiiotool(oiiotool_override)
    cmd = [oiio, str(src), str(stmap), "--st_warp:flip_t=1", "-o", str(dst)]
    _run(cmd, log)
    return dst


def colorconvert(
    src: Path,
    dst: Path,
    src_cs: str,
    dst_cs: str,
    ocio_config: Optional[str] = None,
    log: Optional[LogFn] = None,
    oiiotool_override: Optional[str] = None,
) -> Path:
    """Convert *src* from *src_cs* to *dst_cs* via OCIO and write to *dst*."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    oiio = _find_oiiotool(oiiotool_override)
    cc_args = build_colorconvert_args(src_cs, dst_cs, ocio_config)
    cmd = [oiio, str(src)] + cc_args + ["-o", str(dst)]
    _run(cmd, log)
    return dst


def process_image(
    matched: MatchedSet,
    *,
    source_cs: str,
    exr_output_dir: Optional[Path],
    png_output_dir: Optional[Path],
    acescg_cs: str = "ACES - ACEScg",
    srgb_display_cs: str = "Output - sRGB",
    ocio_config: Optional[str] = None,
    do_undistort: bool = True,
    oiiotool_override: Optional[str] = None,
    log: Optional[LogFn] = None,
) -> dict[str, Optional[Path]]:
    """
    Full processing pipeline for a single MatchedSet.

    Correct order — all pixel interpolation happens in ACEScg linear:

      1. If camera raw → decode to scene-linear EXR (temp, libraw)
      2. oiiotool chain:
           a. Load source (or raw-linear temp)
           b. --colorconvert src_cs → ACEScg   ← into linear FIRST
           c. [stmap] --st_warp                ← warp in linear light
           d. -o <acescg_out.exr>              ← EXR is already ACEScg
           e. --colorconvert ACEScg → sRGB     ← display transform from linear
           f. -o <srgb_out.png>

    Steps b-f are a single chained oiiotool command (oiiotool's -o does not
    pop the stack, so the image remains available for the next operation).

    Returns a dict with keys "exr" and "png" pointing to written files.
    """
    log = log or (lambda s: None)
    oiio = _find_oiiotool(oiiotool_override)
    results: dict[str, Optional[Path]] = {"exr": None, "png": None}

    # Bail early if nothing to produce
    if exr_output_dir is None and png_output_dir is None:
        return results

    with tempfile.TemporaryDirectory(prefix="rc_helper_") as tmp:
        tmp_dir = Path(tmp)

        # ── Step 1: raw decode → scene-linear EXR ───────────────────────
        if matched.is_raw:
            log(f"  Raw decode: {matched.source.name}")
            raw_linear = tmp_dir / (matched.stem + "_raw_linear.exr")
            convert_raw_to_linear(matched.source, raw_linear, log,
                                   oiiotool_override=oiiotool_override)
            working_src = raw_linear
        else:
            working_src = matched.source

        # ── Step 2: build chained oiiotool command ───────────────────────
        # Shared --colorconfig flag (set once, valid for the whole command)
        config_args: list[str] = []
        if ocio_config and Path(ocio_config).exists():
            config_args = ["--colorconfig", ocio_config]

        cmd: list[str] = [oiio, str(working_src)]

        # 2a. Convert to ACEScg linear — interpolation happens here
        log(f"  {source_cs!r} → ACEScg linear")
        cmd += config_args + ["--colorconvert", source_cs, acescg_cs]

        # 2b. Undistort in ACEScg (linear-light bilinear interpolation).
        #     flip_t=1: RC ST maps have T=0 at top; oiiotool expects T=0 at bottom.
        if do_undistort and matched.has_stmap:
            log(f"  Undistorting (ACEScg, flip_t=1): {matched.stmap.name}")
            cmd += [str(matched.stmap), "--st_warp:flip_t=1"]
        elif do_undistort and not matched.has_stmap:
            log(f"  WARNING: no ST map for {matched.source.name}"
                " — skipping undistortion, colour-converting source directly")

        # 2c. Write ACEScg EXR (image is already in working space, no extra convert)
        if exr_output_dir is not None:
            exr_output_dir.mkdir(parents=True, exist_ok=True)
            out_exr = exr_output_dir / (matched.stem + ".exr")
            log(f"  Writing ACEScg EXR: {out_exr.name}")
            cmd += ["-o", str(out_exr)]
            results["exr"] = out_exr

        # 2d. Display transform ACEScg → sRGB, write PNG
        #     oiiotool -o does NOT pop the stack, so ACEScg image is still live
        if png_output_dir is not None:
            png_output_dir.mkdir(parents=True, exist_ok=True)
            out_png = png_output_dir / (matched.stem + ".png")
            log(f"  Writing sRGB display PNG: {out_png.name}")
            cmd += config_args + ["--colorconvert", acescg_cs, srgb_display_cs]
            cmd += ["-o", str(out_png)]
            results["png"] = out_png

        _run(cmd, log)

    return results
