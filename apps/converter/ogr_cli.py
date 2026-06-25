import os
import subprocess
from typing import Optional, List, Tuple
from pathlib import Path

from .models import GeoProcessingJobLog

# ---------------------------------------------------------------------------
# Error catalog (placeholder). In a real project this would be a separate file
# under docs/error-catalog.md and loaded at runtime. Here we define a minimal
# mapping for demonstration purposes.
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    "ogr2ogr": {
        "1": "Failed to open input file",
        "2": "Invalid output format",
        "3": "Layer not found",
    },
    "gdal_translate": {
        "1": "Unsupported input format",
        "2": "Unsupported output format",
    },
}


def _translate_error(tool: str, rc: int) -> str:
    """Return a friendly error message from the catalog if available.

    Args:
        tool: Name of the GDAL tool (e.g., 'ogr2ogr').
        rc:   Return code from the subprocess.
    """
    return ERROR_CATALOG.get(tool, {}).get(str(rc), f"{tool} exited with code {rc}")


def _run_subprocess(cmd: List[str], timeout: int) -> Tuple[int, str, str]:
    """Execute a command with a timeout, capture stdout and stderr.

    Returns a tuple of (returncode, stdout, stderr).
    """
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Process timed out after {timeout}s"


def run_ogr2ogr(
    input_path: str,
    output_path: str,
    output_format: str = "GPKG",
    layer: Optional[str] = None,
    crs: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 1800,
) -> Tuple[int, str, str]:
    """Execute ``ogr2ogr`` for vector‑to‑vector conversion.

    Args:
        input_path:   Path to the source file.
        output_path:  Destination file path.
        output_format: OGR driver name (e.g., 'GPKG', 'GeoJSON', 'ESRI Shapefile').
        layer:        Optional layer name to select when the source contains
                       multiple layers.
        crs:          Target CRS (e.g., 'EPSG:4326').
        extra_args:   Additional CLI arguments as a list of strings.
        timeout:      Maximum seconds to allow the subprocess to run.

    Returns:
        (returncode, stdout, stderr)
    """
    cmd = ["ogr2ogr", "-f", output_format]
    if crs:
        cmd.extend(["-t_srs", crs])
    if layer:
        cmd.extend(["-sql", f"SELECT * FROM {layer}"])
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend([output_path, input_path])

    rc, out, err = _run_subprocess(cmd, timeout)

    if rc == 0:
        GeoProcessingJobLog.objects.create(
            log_level="info",
            message=f"ogr2ogr succeeded: {input_path} → {output_path}",
            details={"stdout": out, "stderr": err},
        )
    else:
        friendly = _translate_error("ogr2ogr", rc)
        GeoProcessingJobLog.objects.create(
            log_level="error",
            message=f"ogr2ogr failed ({friendly})",
            details={"stdout": out, "stderr": err},
        )
    return rc, out, err


def run_gdal_translate(
    input_path: str,
    output_path: str,
    output_format: str = "GTiff",
    crs: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 1800,
) -> Tuple[int, str, str]:
    """Execute ``gdal_translate`` for raster‑to‑raster conversion.

    Args:
        input_path:   Source raster.
        output_path:  Destination raster.
        output_format: GDAL driver name (e.g., 'GTiff', 'PNG').
        crs:          Target CRS (e.g., 'EPSG:4326').
        extra_args:   Additional command‑line flags.
        timeout:      Seconds before the process is aborted.
    """
    cmd = ["gdal_translate", "-of", output_format]
    if crs:
        cmd.extend(["-a_srs", crs])
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend([input_path, output_path])

    rc, out, err = _run_subprocess(cmd, timeout)

    if rc == 0:
        GeoProcessingJobLog.objects.create(
            log_level="info",
            message=f"gdal_translate succeeded: {input_path} → {output_path}",
            details={"stdout": out, "stderr": err},
        )
    else:
        friendly = _translate_error("gdal_translate", rc)
        GeoProcessingJobLog.objects.create(
            log_level="error",
            message=f"gdal_translate failed ({friendly})",
            details={"stdout": out, "stderr": err},
        )
    return rc, out, err
