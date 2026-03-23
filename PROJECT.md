# RC Helper — Project Documentation

## Overview

A PySide6 desktop application for processing exported data from **RealityCapture** photogrammetry software. The tool bridges the gap between raw capture data and VFX pipeline assets by automating undistortion, color management, and Maya camera rig generation.

## Goals

1. **Ingest** source images in any format (JPG, PNG, EXR, camera raw)
2. **Color-manage** images via OCIO — sRGB display for LDR, ACEScg for EXR/raw
3. **Undistort** images using matching ST maps via `oiiotool`
4. **Export** undistorted images in both ACEScg EXR and sRGB-display PNG
5. **Generate** a Maya ASCII scene (`.ma`) with cameras positioned from XMP data, image planes linked to undistorted PNGs

## Target Environment

- **OS**: Windows / Linux
- **Python**: 3.10+ via Conda VFX environment (VFX Reference Platform)
- **GUI**: PySide6
- **Image I/O**: OpenImageIO (`oiiotool` CLI + `OpenImageIO` Python bindings)
- **Color management**: OpenColorIO (PyOpenColorIO Python bindings)
- **3D output**: Maya ASCII `.ma` format (no Maya installation required at runtime)

## Input Data (RealityCapture Export)

| File | Description |
|------|-------------|
| `*.jpg / *.png / *.exr / raw` | Source capture images |
| `*.xmp` | RC camera metadata sidecar — contains position, rotation matrix, focal length, distortion coefficients |
| `stmaps/*.exr` | Spatial transform (ST) maps — per-lens undistortion maps in OpenEXR format |

### XMP Schema (xcr namespace v3)

RC uses the `xcr:` namespace (`http://www.capturingreality.com/ns/xcr/1.1#`) with:

| Attribute / Element | Type | Description |
|---------------------|------|-------------|
| `xcr:FocalLength35mm` | float | Focal length in 35mm-equivalent mm |
| `xcr:PrincipalPointU/V` | float | Principal point offset (normalized -1..1) |
| `xcr:Skew` | float | Camera skew (usually 0) |
| `xcr:AspectRatio` | float | Pixel aspect ratio |
| `xcr:DistortionModel` | string | Distortion model name (e.g. `brown3`) |
| `xcr:Rotation` | 9 floats | Row-major 3×3 world-to-camera rotation matrix |
| `xcr:Position` | 3 floats | Camera centre in world coordinates (metres) |
| `xcr:DistortionCoeficients` | 6 floats | Brown model coefficients k1–k6 |

### Coordinate Convention

- **RC world space**: right-handed, arbitrary orientation (determined by reconstruction)
- **Maya world space**: right-handed, Y-up
- **Conversion**: `R_cam2world = R_world2cam.T`; Euler angles extracted in XYZ intrinsic order; position scaled metres → centimetres (×100)

## Processing Pipeline

```
Source images  ──┐
ST maps        ──┼── file_matcher.py ──► matched triplets (image, stmap, xmp)
XMP sidecars   ──┘
                         │
                         ▼
                  oiio_processor.py
                  ├─ camera raw → linear EXR (oiiotool)
                  ├─ undistort via ST map (oiiotool --st_warp)
                  ├─ OCIO: source CS → ACEScg EXR
                  └─ OCIO: ACEScg → sRGB display PNG
                         │
                         ▼
                  maya_exporter.py
                  ├─ parse XMP → camera matrix
                  ├─ convert to Maya space
                  └─ write .ma with cameras + image planes
```

## Output Structure

```
<output_root>/
├── exr/            # Undistorted ACEScg EXR files
├── png/            # Undistorted sRGB display PNG files
└── maya/
    └── cameras.ma  # Maya ASCII scene
```

## Camera Naming

Maya node names are sanitised: non-alphanumeric characters replaced with `_`, prefixed with `cam_`. If the stem exceeds 24 characters, only the last 14 characters are used (preserving the unique numeric suffix that RC assigns).

## Limitations / Known Issues

- RC world-space orientation is reconstruction-dependent; Y-up is assumed but a coordinate-swap option is planned
- Camera raw support depends on `oiiotool` being built with libraw
- OCIO config must be present in the environment (`$OCIO` env var or user-specified path)
