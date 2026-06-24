"""
CRS policy helpers for reprojection, axis order, and CRS suggestions.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_OPERATIONAL_CRS = "EPSG:4326"
WEB_MAP_CRS = "EPSG:3857"
TRADITIONAL_AXIS_ORDER = "TRADITIONAL_GIS_ORDER"
NTV2_GRID_EXTENSIONS = (".gsb", ".gtx", ".tif", ".tiff")


@dataclass
class CrsSuggestion:
    epsg: str
    name: str
    confidence: str
    reason: str


def configure_axis_order() -> str:
    """Configure GDAL/PROJ to use traditional GIS axis order by default."""
    strategy = os.environ.get("GDAL_AXIS_ORDER", TRADITIONAL_AXIS_ORDER) or TRADITIONAL_AXIS_ORDER
    os.environ.setdefault("OSR_DEFAULT_AXIS_MAPPING_STRATEGY", strategy)
    os.environ.setdefault("OGR_CT_FORCE_TRADITIONAL_GIS_ORDER", "YES")
    return strategy


def normalize_crs(crs: Optional[Any]) -> Optional[str]:
    """Normalize EPSG integers/strings to pyproj-compatible CRS strings."""
    if crs is None:
        return None
    crs_str = str(crs).strip()
    if not crs_str:
        return None
    if crs_str.isdigit():
        return f"EPSG:{crs_str}"
    if crs_str.upper().startswith("EPSG:"):
        return f"EPSG:{crs_str.split(':', 1)[1].strip()}"
    return crs_str


def crs_to_epsg(crs: Any) -> Optional[int]:
    if crs is None:
        return None
    try:
        if hasattr(crs, "to_epsg"):
            return crs.to_epsg()
        from pyproj import CRS

        return CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


def _crs_display(crs: Any) -> Optional[str]:
    if crs is None:
        return None
    epsg = crs_to_epsg(crs)
    if epsg:
        return f"EPSG:{epsg}"
    try:
        return crs.to_string()
    except Exception:
        return str(crs)


def apply_source_crs(gdf, source_crs: Optional[Any] = None, target_crs: Optional[Any] = None):
    """
    Apply manual source CRS override and reject target reprojection when source is unknown.
    """
    configure_axis_order()
    source = normalize_crs(source_crs)
    target = normalize_crs(target_crs)

    if source:
        return gdf.set_crs(source, allow_override=True)

    if target and gdf.crs is None:
        raise ValueError(
            "Source CRS is unknown. Provide a manual source CRS before running reprojection."
        )
    return gdf


def resolve_raster_source_crs(src, source_crs: Optional[Any] = None, target_crs: Optional[Any] = None):
    """
    Resolve raster source CRS, rejecting target reprojection when no source/override exists.
    """
    configure_axis_order()
    source = normalize_crs(source_crs)
    target = normalize_crs(target_crs)
    if source:
        return source
    if src.crs is not None:
        return src.crs
    if target:
        raise ValueError(
            "Source CRS is unknown. Provide a manual source CRS before running reprojection."
        )
    return None


def _bbox_values(bbox: Any) -> Optional[Dict[str, float]]:
    if not bbox:
        return None
    if isinstance(bbox, dict):
        keys = {
            "minx": ("minx", "x_min", "left"),
            "maxx": ("maxx", "x_max", "right"),
            "miny": ("miny", "y_min", "bottom"),
            "maxy": ("maxy", "y_max", "top"),
        }
        out = {}
        for name, aliases in keys.items():
            for alias in aliases:
                if alias in bbox and bbox[alias] is not None:
                    out[name] = float(bbox[alias])
                    break
        if len(out) == 4:
            return out
    return None


def suggest_crs_by_extent(bbox: Any) -> List[CrsSuggestion]:
    """
    Return advisory CRS guesses based on extent. Operators must confirm manually.
    """
    values = _bbox_values(bbox)
    if not values:
        return []

    minx, maxx = values["minx"], values["maxx"]
    miny, maxy = values["miny"], values["maxy"]
    suggestions: List[CrsSuggestion] = []

    if -180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90:
        suggestions.append(CrsSuggestion(
            "EPSG:4326",
            "WGS 84",
            "high",
            "Extent values fit longitude/latitude degrees.",
        ))

    if all(-20037509 <= v <= 20037509 for v in (minx, maxx)) and all(-20048967 <= v <= 20048967 for v in (miny, maxy)):
        if max(abs(minx), abs(maxx), abs(miny), abs(maxy)) > 180:
            suggestions.append(CrsSuggestion(
                "EPSG:3857",
                "WGS 84 / Web Mercator",
                "medium",
                "Extent values fit Web Mercator meters.",
            ))

    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2
    if -180 <= center_lon <= 180 and -80 <= center_lat <= 84:
        zone = int((center_lon + 180) // 6) + 1
        epsg = 32600 + zone if center_lat >= 0 else 32700 + zone
        suggestions.append(CrsSuggestion(
            f"EPSG:{epsg}",
            f"WGS 84 / UTM zone {zone}{'N' if center_lat >= 0 else 'S'}",
            "low",
            "Centroid falls inside a UTM zone; useful for projected local data.",
        ))

    deduped = []
    seen = set()
    for suggestion in suggestions:
        if suggestion.epsg not in seen:
            deduped.append(suggestion)
            seen.add(suggestion.epsg)
    return deduped[:4]


def suggestions_to_dicts(suggestions: Iterable[CrsSuggestion]) -> List[Dict[str, str]]:
    return [suggestion.__dict__ for suggestion in suggestions]


def discover_ntv2_grids(grid_dirs: Optional[Iterable[str]] = None) -> List[Dict[str, str]]:
    """List locally available NTv2/PROJ grid files."""
    candidates = list(grid_dirs or [])
    proj_data = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
    if proj_data:
        candidates.append(proj_data)

    found = []
    seen = set()
    for directory in candidates:
        if not directory or not os.path.isdir(directory):
            continue
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                if filename.lower().endswith(NTV2_GRID_EXTENSIONS):
                    path = os.path.join(root, filename)
                    if path not in seen:
                        found.append({"name": filename, "path": path})
                        seen.add(path)
    return found


configure_axis_order()
