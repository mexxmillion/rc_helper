"""
xmp_parser.py
-------------
Parse RealityCapture XMP sidecar files (xcr namespace v3).

XMP structure (relevant fields):
  xcr:Rotation        — 9 floats, row-major 3×3 world-to-camera rotation matrix
  xcr:Position        — 3 floats, camera centre in world space (metres)
  xcr:FocalLength35mm — float, focal length in 35mm-equivalent mm
  xcr:PrincipalPointU/V — float, principal point offset (normalised -1..1)
  xcr:AspectRatio     — float, pixel aspect ratio
  xcr:Skew            — float
  xcr:DistortionModel — str
  xcr:DistortionCoeficients — 6 floats, Brown k1-k6
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

XCR_NS = "http://www.capturingreality.com/ns/xcr/1.1#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


@dataclass
class CameraData:
    """Camera parameters parsed from an RC XMP sidecar."""
    source_stem: str  # e.g. "1_YukihiroIwayama"
    xmp_path: Path

    # Extrinsics
    position: np.ndarray = field(default_factory=lambda: np.zeros(3))
    """Camera centre in RC world space (metres)."""

    rotation_w2c: np.ndarray = field(default_factory=lambda: np.eye(3))
    """World-to-camera rotation matrix (3×3, row-major)."""

    # Intrinsics
    focal_length_35mm: float = 35.0
    principal_point_u: float = 0.0
    principal_point_v: float = 0.0
    aspect_ratio: float = 1.0
    skew: float = 0.0

    # Distortion
    distortion_model: str = "brown3"
    distortion_coefficients: list[float] = field(default_factory=list)

    @property
    def rotation_c2w(self) -> np.ndarray:
        """Camera-to-world rotation (transpose of world-to-camera)."""
        return self.rotation_w2c.T

    @property
    def euler_xyz_deg(self) -> tuple[float, float, float]:
        """
        Camera orientation as Maya XYZ Euler angles (degrees).

        RC camera space uses OpenCV convention: X right, Y down, Z into scene.
        Maya camera space:                       X right, Y up,   Z out of scene.
        Conversion: post-multiply R_c2w by diag(1, -1, -1) to flip Y and Z.
        """
        flip = np.diag([1.0, -1.0, -1.0])
        R = self.rotation_c2w @ flip
        return _rotation_matrix_to_euler_xyz(R)

    @property
    def position_cm(self) -> np.ndarray:
        """
        Camera position passed through as-is (RC metres treated as Maya units).
        VFX pipelines work at metre scale in Maya even when the unit label is cm.
        """
        return self.position


def parse_xmp(xmp_path: str | Path) -> CameraData:
    """Parse a single RC XMP file and return a CameraData instance."""
    xmp_path = Path(xmp_path)
    source_stem = xmp_path.stem  # e.g. "1_YukihiroIwayama"

    tree = ET.parse(xmp_path)
    root = tree.getroot()

    # Find the rdf:Description element
    desc = root.find(f".//{{{RDF_NS}}}Description")
    if desc is None:
        raise ValueError(f"No rdf:Description found in {xmp_path}")

    cam = CameraData(source_stem=source_stem, xmp_path=xmp_path)

    # ── Intrinsics from attributes ────────────────────────────────────────
    def _attr(name: str, default=None):
        return desc.get(f"{{{XCR_NS}}}{name}", default)

    raw_fl = _attr("FocalLength35mm")
    if raw_fl is not None:
        cam.focal_length_35mm = float(raw_fl)

    raw_ppu = _attr("PrincipalPointU")
    if raw_ppu is not None:
        cam.principal_point_u = float(raw_ppu)

    raw_ppv = _attr("PrincipalPointV")
    if raw_ppv is not None:
        cam.principal_point_v = float(raw_ppv)

    raw_ar = _attr("AspectRatio")
    if raw_ar is not None:
        cam.aspect_ratio = float(raw_ar)

    raw_skew = _attr("Skew")
    if raw_skew is not None:
        cam.skew = float(raw_skew)

    raw_dm = _attr("DistortionModel")
    if raw_dm is not None:
        cam.distortion_model = raw_dm

    # ── Rotation (child element) ──────────────────────────────────────────
    rot_el = desc.find(f"{{{XCR_NS}}}Rotation")
    if rot_el is not None and rot_el.text:
        vals = [float(v) for v in rot_el.text.split()]
        if len(vals) == 9:
            cam.rotation_w2c = np.array(vals, dtype=np.float64).reshape(3, 3)

    # ── Position (child element) ──────────────────────────────────────────
    pos_el = desc.find(f"{{{XCR_NS}}}Position")
    if pos_el is not None and pos_el.text:
        vals = [float(v) for v in pos_el.text.split()]
        if len(vals) == 3:
            cam.position = np.array(vals, dtype=np.float64)

    # ── Distortion coefficients ───────────────────────────────────────────
    dist_el = desc.find(f"{{{XCR_NS}}}DistortionCoeficients")
    if dist_el is not None and dist_el.text:
        cam.distortion_coefficients = [float(v) for v in dist_el.text.split()]

    return cam


def _rotation_matrix_to_euler_xyz(R: np.ndarray) -> tuple[float, float, float]:
    """
    Extract XYZ intrinsic Euler angles (in degrees) from a 3×3 rotation matrix.

    This decomposes R = Rx(x) @ Ry(y) @ Rz(z).
    """
    import math

    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6

    if not singular:
        x = math.atan2(R[2, 1], R[2, 2])
        y = math.atan2(-R[2, 0], sy)
        z = math.atan2(R[1, 0], R[0, 0])
    else:
        x = math.atan2(-R[1, 2], R[1, 1])
        y = math.atan2(-R[2, 0], sy)
        z = 0.0

    return math.degrees(x), math.degrees(y), math.degrees(z)
