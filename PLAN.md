# RC Helper — Implementation Plan

## Phase 1: Project scaffold & .gitignore ✅
- [x] `.gitignore` — exclude large image/raw/DB files from Git
- [x] `PROJECT.md` — full project documentation
- [x] `PLAN.md` — this file
- [x] `requirements.txt` — Python dependencies

## Phase 2: Core processing modules
- [x] `src/rc_helper/core/file_matcher.py` — pair images ↔ stmaps ↔ xmps
- [x] `src/rc_helper/core/xmp_parser.py` — parse RC XMP sidecars
- [x] `src/rc_helper/core/ocio_utils.py` — OCIO config loading & color space queries
- [x] `src/rc_helper/core/oiio_processor.py` — oiiotool subprocess wrapper
- [x] `src/rc_helper/core/maya_exporter.py` — Maya ASCII .ma writer
- [x] `src/rc_helper/core/processor.py` — orchestration pipeline

## Phase 3: PySide6 UI
- [x] `src/rc_helper/ui/main_window.py` — main window, menu, layout
- [x] `src/rc_helper/ui/source_panel.py` — source image folder + color space options
- [x] `src/rc_helper/ui/stmap_panel.py` — ST map folder + pair preview
- [x] `src/rc_helper/ui/output_panel.py` — output folder selection (EXR / PNG / Maya)
- [x] `src/rc_helper/ui/process_panel.py` — toggle options + process button + log

## Phase 4: Entry point
- [x] `main.py` — app bootstrap

---

## Module Responsibilities

### `file_matcher.py`
- Scan source folder for supported image extensions
- Scan stmaps folder for `*.stmap.exr` files
- Match by stem (e.g. `1_YukihiroIwayama.jpg` ↔ `1_YukihiroIwayama.jpg.stmap.exr`)
- Optionally match `*.xmp` sidecars alongside source images
- Return list of `MatchedSet` dataclasses

### `xmp_parser.py`
- Parse `xcr:Rotation` → numpy 3×3 float64 matrix (world-to-camera)
- Parse `xcr:Position` → numpy 3-vector (camera centre, world space)
- Parse `xcr:FocalLength35mm`, `PrincipalPointU/V`, `AspectRatio`
- Return `CameraData` dataclass

### `ocio_utils.py`
- Load OCIO config from `$OCIO` or user-provided path
- Return list of color space names for UI dropdowns
- Provide helper: `build_oiiotool_colorconvert_args(src_cs, dst_cs)`

### `oiio_processor.py`
- `convert_raw_to_linear(src, dst)` — camera raw → linear EXR
- `undistort_with_stmap(src, stmap, dst)` — apply ST warp
- `colorconvert(src, dst, src_cs, dst_cs, ocio_config)` — OCIO color convert
- `process_image(matched_set, settings)` — full pipeline for one image
- All operations run `oiiotool` as a subprocess; stdout/stderr captured and forwarded to UI log

### `maya_exporter.py`
- Accept list of `CameraData` + undistorted PNG paths
- Convert RC world→camera rotation to Maya camera-to-world Euler XYZ
- Scale position: metres × 100 = centimetres (Maya default)
- Film aperture: 36 mm × 24 mm (1.41732 × 0.94488 inches)
- Write Maya ASCII header, `createNode transform/camera/imagePlane`, `connectAttr`
- Sanitise node names; truncate stems > 24 chars to last 14 chars

### `processor.py`
- `ProcessSettings` dataclass — all user choices
- `run(settings, progress_callback, log_callback)` — iterate matched sets, call modules
- Worker runs in a `QThread` so UI stays responsive

### `main_window.py`
- Central widget with splitter: left panels (source, stmap, output) | right log
- Bottom bar: option toggles + Process button
- Connects worker thread signals to progress bar and log widget

---

## oiiotool Command Reference

```bash
# Undistort with ST map
oiiotool <source> <stmap> --st_warp -o <output>

# OCIO color convert
oiiotool --colorconfig <config.ocio> <input> \
    --colorconvert "<src_cs>" "<dst_cs>" -o <output>

# Chain: undistort → color convert to ACEScg EXR
oiiotool <source> <stmap> --st_warp \
    --colorconfig <config.ocio> \
    --colorconvert "<src_cs>" "ACES - ACEScg" \
    -o <output>.exr

# Chain: undistort → color convert to sRGB display PNG
oiiotool <source> <stmap> --st_warp \
    --colorconfig <config.ocio> \
    --colorconvert "<src_cs>" "Output - sRGB" \
    -o <output>.png

# Camera raw → linear (oiiotool reads via libraw)
oiiotool <raw_file> -o <linear>.exr
```

---

## Maya ASCII Camera Structure

```
//Maya ASCII 2024 scene
requires maya "2024";
currentUnit -l centimeter -a degree -t film;

createNode transform -n "cam_<name>_grp";
    setAttr ".t" -type "double3" <tx> <ty> <tz>;
    setAttr ".r" -type "double3" <rx> <ry> <rz>;

createNode camera -n "cam_<name>" -p "cam_<name>_grp";
    setAttr ".fl" <focal_length_mm>;
    setAttr ".cap" -type "double2" 1.41732 0.94488;

createNode imagePlane -n "cam_<name>_imgPlane" -p "cam_<name>";
    setAttr ".fn" -type "string" "<abs_path_to_undistorted.png>";
    setAttr ".fc" 1;
    setAttr ".d" 100;

connectAttr "cam_<name>_imgPlane.message" "cam_<name>.imagePlane" -na;
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `oiiotool` subprocess (not Python bindings) | More stable across VFX platform versions; easier to test manually |
| OCIO via Python bindings for UI | Fast color space enumeration without spawning a process |
| QThread worker | Keeps UI responsive during long batch jobs |
| Metres → centimetres ×100 | Maya default unit is centimetres; RC exports in metres |
| 35mm film gate assumption | Safest default without knowing actual sensor size |
| Last-14-chars naming | Preserves numeric ID that makes RC names unique |
