"""
check_maya.py
-------------
Read and validate an RC Helper-generated Maya ASCII (.ma) file.

Usage:
    python check_maya.py <path_to_cameras.ma>
    python check_maya.py          # defaults to images/maya/cameras.ma

Reports:
  - Camera count
  - Per-camera: name, focal length, position, rotation
  - Image plane path for each camera and whether the file exists on disk
  - Summary: missing image files
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_CREATE_TRANSFORM = re.compile(
    r'createNode transform -n "([^"]+_grp)"'
)
_RE_TRANSLATE = re.compile(
    r'setAttr "\.t" -type "double3"\s+([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)'
)
_RE_ROTATE = re.compile(
    r'setAttr "\.r" -type "double3"\s+([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)'
)
_RE_CREATE_CAMERA = re.compile(
    r'createNode camera -n "([^"]+Shape)"'
)
_RE_FOCAL = re.compile(r'setAttr "\.fl"\s+([\d.]+)')
_RE_CREATE_IMGPLANE = re.compile(
    r'createNode imagePlane -n "([^"]+)"'
)
_RE_FILENAME = re.compile(
    r'setAttr "\.fn" -type "string" "([^"]+)"'
)


@dataclass
class CameraEntry:
    grp_name: str = ""
    shape_name: str = ""
    tx: float = 0.0
    ty: float = 0.0
    tz: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    focal_length: float = 0.0
    image_plane: str = ""    # empty → no image plane


def parse_ma(ma_path: Path) -> list[CameraEntry]:
    """Parse a Maya ASCII file written by RC Helper and return camera entries."""
    text = ma_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    cameras: list[CameraEntry] = []
    current: CameraEntry | None = None
    in_imgplane = False

    for line in lines:
        stripped = line.strip()

        # ── New group (one per camera) ────────────────────────────────────
        m = _RE_CREATE_TRANSFORM.search(stripped)
        if m:
            current = CameraEntry(grp_name=m.group(1))
            cameras.append(current)
            in_imgplane = False
            continue

        if current is None:
            continue

        # ── Camera shape ──────────────────────────────────────────────────
        m = _RE_CREATE_CAMERA.search(stripped)
        if m:
            current.shape_name = m.group(1)
            in_imgplane = False
            continue

        # ── Image plane node ──────────────────────────────────────────────
        m = _RE_CREATE_IMGPLANE.search(stripped)
        if m:
            in_imgplane = True
            continue

        # ── Attributes ────────────────────────────────────────────────────
        m = _RE_TRANSLATE.search(stripped)
        if m and not in_imgplane:
            current.tx, current.ty, current.tz = (
                float(m.group(1)), float(m.group(2)), float(m.group(3))
            )
            continue

        m = _RE_ROTATE.search(stripped)
        if m and not in_imgplane:
            current.rx, current.ry, current.rz = (
                float(m.group(1)), float(m.group(2)), float(m.group(3))
            )
            continue

        m = _RE_FOCAL.search(stripped)
        if m and not in_imgplane:
            current.focal_length = float(m.group(1))
            continue

        m = _RE_FILENAME.search(stripped)
        if m and in_imgplane:
            current.image_plane = m.group(1)
            in_imgplane = False
            continue

    return cameras


def check(ma_path: Path) -> None:
    print(f"\n{'='*64}")
    print(f"  RC Helper Maya checker")
    print(f"  File : {ma_path}")
    print(f"{'='*64}\n")

    if not ma_path.exists():
        print(f"  ERROR: file not found: {ma_path}")
        return

    cameras = parse_ma(ma_path)

    if not cameras:
        print("  No cameras found in file.")
        return

    missing_images: list[str] = []
    no_imgplane: list[str] = []

    col_w = max(len(c.grp_name) for c in cameras) + 2

    # Header
    print(f"  {'Camera':<{col_w}}  {'FL(mm)':>7}  {'Tx':>10} {'Ty':>10} {'Tz':>10}  Image plane")
    print(f"  {'-'*col_w}  {'-'*7}  {'-'*10} {'-'*10} {'-'*10}  {'-'*40}")

    for cam in cameras:
        ip = cam.image_plane
        if not ip:
            ip_display = "  [NO IMAGE PLANE]"
            no_imgplane.append(cam.grp_name)
        else:
            exists = Path(ip).exists()
            marker = "OK" if exists else "MISSING"
            ip_display = f"  [{marker}] {ip}"
            if not exists:
                missing_images.append(ip)

        print(
            f"  {cam.grp_name:<{col_w}}  {cam.focal_length:>7.2f}  "
            f"{cam.tx:>10.2f} {cam.ty:>10.2f} {cam.tz:>10.2f}"
            f"{ip_display}"
        )

    # Summary
    total = len(cameras)
    with_ip = total - len(no_imgplane)
    ok_ip = with_ip - len(missing_images)

    print(f"\n{'='*64}")
    print(f"  Cameras         : {total}")
    print(f"  With image plane: {with_ip} / {total}")
    print(f"  Image files OK  : {ok_ip} / {with_ip}")

    if no_imgplane:
        print(f"\n  Cameras WITHOUT image plane ({len(no_imgplane)}):")
        for name in no_imgplane:
            print(f"    - {name}")

    if missing_images:
        print(f"\n  Missing image files ({len(missing_images)}):")
        for p in missing_images:
            print(f"    - {p}")
    elif with_ip > 0:
        print(f"\n  All image files found on disk.")

    print(f"{'='*64}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path(__file__).parent / "images" / "maya" / "cameras.ma"

    check(target)
