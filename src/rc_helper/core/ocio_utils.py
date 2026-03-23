"""
ocio_utils.py
-------------
OpenColorIO helpers: config discovery, color space enumeration, and
oiiotool argument construction for color conversion.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

# PyOpenColorIO is part of the VFX conda environment
try:
    import PyOpenColorIO as OCIO  # type: ignore
    _OCIO_AVAILABLE = True
except ImportError:
    _OCIO_AVAILABLE = False

# ── Well-known color space name patterns ──────────────────────────────────────
# These are searched (case-insensitive substring) to pick sensible defaults.

_LDR_DEFAULT_PATTERNS = ["srgb texture", "input - srgb", "srgb - texture",
                          "utility - srgb", "srgb"]
_HDR_DEFAULT_PATTERNS = ["aces - acescg", "acescg", "linear"]
_DISPLAY_SRGB_PATTERNS = ["output - srgb", "srgb display", "srgb"]
_ACESCG_PATTERNS = ["aces - acescg", "acescg"]


@lru_cache(maxsize=1)
def load_config(config_path: Optional[str] = None) -> Optional[object]:
    """
    Load an OCIO config.  Priority:
    1. *config_path* argument
    2. ``$OCIO`` environment variable
    3. OCIO built-in default (if available)

    Returns the config object, or None if OCIO is not available.
    """
    if not _OCIO_AVAILABLE:
        return None

    if config_path:
        return OCIO.Config.CreateFromFile(config_path)

    ocio_env = os.environ.get("OCIO", "")
    if ocio_env and Path(ocio_env).exists():
        return OCIO.Config.CreateFromFile(ocio_env)

    try:
        return OCIO.GetCurrentConfig()
    except Exception:
        return None


def get_color_spaces(config_path: Optional[str] = None) -> list[str]:
    """Return all color space names in the loaded config."""
    cfg = load_config(config_path)
    if cfg is None:
        return _fallback_color_spaces()
    # OCIO 2.x: getColorSpaces() returns an iterable of ColorSpace objects
    return [cs.getName() for cs in cfg.getColorSpaces()]


def _fallback_color_spaces() -> list[str]:
    """Minimal list when OCIO is unavailable."""
    return [
        "sRGB",
        "Linear",
        "ACEScg",
        "ACES2065-1",
        "raw",
    ]


def find_color_space(names: list[str], patterns: list[str]) -> Optional[str]:
    """Return the first name that contains any of *patterns* (case-insensitive)."""
    for pattern in patterns:
        for name in names:
            if pattern.lower() in name.lower():
                return name
    return names[0] if names else None


def default_ldr_source(config_path: Optional[str] = None) -> str:
    spaces = get_color_spaces(config_path)
    return find_color_space(spaces, _LDR_DEFAULT_PATTERNS) or "sRGB"


def default_hdr_source(config_path: Optional[str] = None) -> str:
    spaces = get_color_spaces(config_path)
    return find_color_space(spaces, _HDR_DEFAULT_PATTERNS) or "ACEScg"


def default_display_srgb(config_path: Optional[str] = None) -> str:
    spaces = get_color_spaces(config_path)
    return find_color_space(spaces, _DISPLAY_SRGB_PATTERNS) or "sRGB"


def default_acescg(config_path: Optional[str] = None) -> str:
    spaces = get_color_spaces(config_path)
    return find_color_space(spaces, _ACESCG_PATTERNS) or "ACEScg"


def build_colorconvert_args(
    src_cs: str,
    dst_cs: str,
    config_path: Optional[str] = None,
) -> list[str]:
    """
    Build the oiiotool fragment for a color conversion.

    Returns a list of arguments to be inserted into an oiiotool command,
    e.g. ``["--colorconfig", "/path/config.ocio", "--colorconvert", "sRGB", "ACEScg"]``
    """
    args: list[str] = []

    ocio_path = config_path or os.environ.get("OCIO", "")
    if ocio_path and Path(ocio_path).exists():
        args += ["--colorconfig", ocio_path]

    args += ["--colorconvert", src_cs, dst_cs]
    return args
