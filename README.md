# RC Helper

A PySide6 desktop tool for processing **RealityCapture** photogrammetry exports in a VFX pipeline.

## Features

- Ingest source images: JPG, PNG, EXR, TIFF, camera raw (CR2, CR3, ARW, NEF, DNG, …)
- OCIO color management — configurable source color space, ACEScg EXR and sRGB display PNG outputs
- Undistortion via ST maps using `oiiotool --st_warp`
- Parses RC XMP sidecars to extract camera position, rotation, and focal length
- Generates a Maya ASCII `.ma` scene with cameras and image planes

## Quick Start

```bash
# activate your conda VFX environment, then:
python main.py
```

Requires `oiiotool` on `$PATH` and `$OCIO` pointing to a valid OCIO config.

## Docs

- [PROJECT.md](PROJECT.md) — full technical specification
- [PLAN.md](PLAN.md) — implementation plan and command reference
