"""
maya_exporter.py
----------------
Generate a Maya ASCII (.ma) scene from RC camera data.

Each camera gets:
  - A transform node  (position + rotation from XMP)
  - A camera shape    (focal length from XMP, 35mm film gate)
  - An imagePlane     (linked to the corresponding undistorted PNG)

Coordinate conversion
---------------------
  RC position  (metres)   → Maya translate (centimetres, ×100)
  RC rotation  R_w2c      → Maya rotate: Euler XYZ from R_c2w = R_w2c.T
  Film gate               → 36 mm × 24 mm  (1.41732 × 0.94488 inches)

Camera naming
-------------
  Stem is sanitised (non-alphanumeric → '_').
  If the sanitised stem is longer than 24 characters, the last 14 chars are used.
  Final name is prefixed with 'cam_'.

Maya ASCII structure
--------------------
  All createNode / setAttr blocks must appear before any connectAttr lines.
  This module splits output into (nodes, connects) and writes them in order.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .xmp_parser import CameraData

# Maya film aperture for 35mm full frame (in inches)
_FILM_H_INCH = 36.0 / 25.4   # 1.41732...
_FILM_V_INCH = 24.0 / 25.4   # 0.94488...

_MAX_STEM = 24
_SHORT_STEM = 14


def _sanitise_name(stem: str) -> str:
    """Convert a filename stem to a valid Maya node name prefix."""
    sanitised = re.sub(r"[^A-Za-z0-9]", "_", stem)
    if len(sanitised) > _MAX_STEM:
        sanitised = sanitised[-_SHORT_STEM:]
    if sanitised and sanitised[0].isdigit():
        sanitised = "n" + sanitised
    return sanitised


def _camera_block(
    cam: CameraData,
    png_path: Optional[Path],
    index: int,
) -> tuple[str, str]:
    """
    Return (nodes_text, connects_text) for one camera + image plane.

    nodes_text   — all createNode / setAttr lines
    connects_text — all connectAttr lines (must go after ALL nodes in the file)
    """
    safe = _sanitise_name(cam.source_stem)
    cam_xform = f"cam_{safe}"          # camera transform
    cam_shape = f"cam_{safe}Shape"     # camera shape
    ip_xform  = f"imagePlane_{safe}"   # imagePlane transform (parented to cam shape)
    ip_shape  = f"imagePlane_{safe}Shape"  # imagePlane shape

    tx, ty, tz = cam.position_cm
    rx, ry, rz = cam.euler_xyz_deg
    fl = cam.focal_length_35mm

    nodes: list[str] = []
    connects: list[str] = []

    # ── Camera transform ──────────────────────────────────────────────────
    nodes.append(f'createNode transform -n "{cam_xform}";')
    nodes.append(f'\trename -uid "CAM_XFORM_{index:04d}";')
    nodes.append(f'\tsetAttr ".t" -type "double3" {tx:.6f} {ty:.6f} {tz:.6f};')
    nodes.append(f'\tsetAttr ".r" -type "double3" {rx:.6f} {ry:.6f} {rz:.6f};')
    nodes.append("")

    # ── Camera shape (child of transform) ────────────────────────────────
    nodes.append(f'createNode camera -n "{cam_shape}" -p "{cam_xform}";')
    nodes.append(f'\trename -uid "CAM_SHAPE_{index:04d}";')
    nodes.append(f'\tsetAttr ".fl" {fl:.6f};')
    nodes.append(f'\tsetAttr ".cap" -type "double2" {_FILM_H_INCH:.6f} {_FILM_V_INCH:.6f};')
    nodes.append("")

    # ── Image plane (only when a PNG path is available) ───────────────────
    # Structure mirrors Maya's own export:
    #   imagePlane transform → parented to camera SHAPE
    #   imagePlane shape     → parented to imagePlane transform
    # connectAttr lines are returned separately and written at end of file.
    if png_path is not None:
        png_str = str(png_path).replace("\\", "/")

        nodes.append(f'createNode transform -n "{ip_xform}" -p "{cam_shape}";')
        nodes.append(f'\trename -uid "IP_XFORM_{index:04d}";')
        nodes.append("")

        nodes.append(f'createNode imagePlane -n "{ip_shape}" -p "{ip_xform}";')
        nodes.append(f'\trename -uid "IP_SHAPE_{index:04d}";')
        nodes.append(f'\tsetAttr ".fc" 1;')
        nodes.append(f'\tsetAttr ".imn" -type "string" "{png_str}";')
        nodes.append(f'\tsetAttr ".d" 100;')
        nodes.append(f'\tsetAttr ".fit" 4;')
        nodes.append(f'\tsetAttr ".s" -type "double2" {_FILM_H_INCH:.6f} {_FILM_V_INCH:.6f};')
        nodes.append("")

        # Connections — collected here, written at END of file
        connects.append(f'connectAttr "{ip_shape}.msg" "{cam_shape}.ip" -na;')
        connects.append(f'connectAttr ":defaultColorMgtGlobals.cme" "{ip_shape}.cme";')
        connects.append(f'connectAttr ":defaultColorMgtGlobals.cfe" "{ip_shape}.cmcf";')
        connects.append(f'connectAttr ":defaultColorMgtGlobals.cfp" "{ip_shape}.cmcp";')
        connects.append(f'connectAttr ":defaultColorMgtGlobals.wsn" "{ip_shape}.ws";')
        connects.append("")

    return "\n".join(nodes), "\n".join(connects)


def write_maya_scene(
    cameras: list[CameraData],
    png_paths: dict[str, Optional[Path]],
    output_path: str | Path,
    scene_unit: str = "centimeter",
) -> Path:
    """
    Write a Maya ASCII file containing all cameras and image planes.

    Parameters
    ----------
    cameras:
        List of CameraData parsed from XMP files.
    png_paths:
        Mapping from source stem to the corresponding undistorted PNG path
        (or None if no PNG was produced for that stem).
    output_path:
        Destination .ma file path.
    scene_unit:
        Maya linear unit (default "centimeter").
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    header = f"""\
//Maya ASCII 2024 scene
//Name: {output_path.name}
//Generated by RC Helper on {now}
//Codeset: UTF-8
requires maya "2024";
currentUnit -l {scene_unit} -a degree -t film;
fileInfo "application" "RC Helper";
fileInfo "product" "RC Helper 0.1.0";

"""

    all_nodes: list[str] = []
    all_connects: list[str] = []

    for idx, cam in enumerate(cameras):
        png = png_paths.get(cam.source_stem)
        nodes_text, connects_text = _camera_block(cam, png, idx)
        all_nodes.append(nodes_text)
        if connects_text.strip():
            all_connects.append(connects_text)

    # Maya ASCII rule: ALL createNode/setAttr FIRST, then ALL connectAttr
    content = header + "\n".join(all_nodes)
    if all_connects:
        content += "\n" + "\n".join(all_connects)

    output_path.write_text(content, encoding="utf-8")
    return output_path
