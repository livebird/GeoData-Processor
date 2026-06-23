"""
GDAL/OGR Conversion Module (Python API implementation)

This module implements geospatial data conversions using the Python GDAL
ecosystem (rasterio, geopandas, fiona, shapely) instead of CLI tools,
so it works without GDAL binaries on the system PATH.

Equivalent functionality to:
- gdal_translate    → rasterio
- ogr2ogr           → geopandas / fiona
- gdal_rasterize    → rasterio.features.rasterize
- gdal_polygonize   → rasterio.features.shapes
"""

import os
from typing import List, Optional


# ---------------------------------------------------------------------------
# Availability check (non-fatal; callers can decide what to do)
# ---------------------------------------------------------------------------

def check_gdal_tools() -> bool:
    """
    Check whether the Python GDAL ecosystem is available.
    Returns True if all required packages are importable.
    Raises RuntimeError listing missing packages if any are absent.
    """
    missing = []
    for pkg in ("rasterio", "geopandas", "fiona", "shapely"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        raise RuntimeError(
            f"Required Python packages not found: {', '.join(missing)}. "
            "Install them with: pip install rasterio geopandas fiona shapely"
        )
    return True


# ---------------------------------------------------------------------------
# Raster → Raster  (replaces gdal_translate)
# ---------------------------------------------------------------------------

def raster_to_raster(input_path: str, output_path: str, output_format: str = "GTiff",
                     crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert raster to raster using rasterio.

    Args:
        input_path: Path to input raster file
        output_path: Path to output raster file
        output_format: Output format (GTiff, PNG, JPEG, etc.)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: nodata value (kwarg 'nodata')

    Returns:
        Path to output file
    """
    import rasterio
    from rasterio.crs import CRS as RasterioCRS

    driver_map = {"GTiff": "GTiff", "GeoTIFF": "GTiff", "PNG": "PNG",
                  "JPEG": "JPEG", "JPG": "JPEG", "GPKG": "GPKG"}
    rasterio_driver = driver_map.get(output_format, output_format)

    print(f"[rasterio] Converting raster: {input_path} → {output_path} (driver={rasterio_driver})")

    with rasterio.open(input_path) as src:
        if crs:
            from rasterio.warp import calculate_default_transform, reproject, Resampling
            dst_crs = RasterioCRS.from_string(crs)
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds
            )
            profile = src.profile.copy()
            profile.update(driver=rasterio_driver, crs=dst_crs,
                           transform=transform, width=width, height=height)
            if kwargs.get("nodata") is not None:
                profile["nodata"] = kwargs["nodata"]
            with rasterio.open(output_path, "w", **profile) as dst:
                for band_idx in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, band_idx),
                        destination=rasterio.band(dst, band_idx),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=dst_crs,
                        resampling=Resampling.nearest,
                    )
        else:
            profile = src.profile.copy()
            profile.update(driver=rasterio_driver)
            if kwargs.get("nodata") is not None:
                profile["nodata"] = kwargs["nodata"]
            data = src.read()
            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(data)

    print(f"[OK] Converted: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Vector → Vector  (replaces ogr2ogr)
# ---------------------------------------------------------------------------

def vector_to_vector(input_path: str, output_path: str, output_format: str = "GeoJSON",
                     crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert vector to vector using geopandas / fiona.

    Args:
        input_path: Path to input vector file
        output_path: Path to output vector file
        output_format: OGR driver name (ESRI Shapefile, GeoJSON, GPKG, KML, …)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: layer_name (str)

    Returns:
        Path to output file
    """
    import geopandas as gpd

    print(f"[geopandas] Converting vector: {input_path} → {output_path} (driver={output_format})")

    gdf = gpd.read_file(input_path)

    if crs:
        if gdf.crs is not None:
            gdf = gdf.to_crs(crs)
        else:
            gdf = gdf.set_crs(crs)

    driver_map = {"GeoPackage": "GPKG", "KMZ": "LIBKML"}
    fiona_driver = driver_map.get(output_format, output_format)

    gdf.to_file(output_path, driver=fiona_driver)
    print(f"[OK] Converted: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Vector → Raster  (replaces gdal_rasterize)
# ---------------------------------------------------------------------------

def vector_to_raster(input_path: str, output_path: str, output_format: str = "GTiff",
                     burn_value: int = 255, crs: Optional[str] = None,
                     resolution: Optional[float] = None, **kwargs) -> str:
    """
    Convert vector to raster using rasterio.features.rasterize.

    Args:
        input_path: Path to input vector file
        output_path: Path to output raster file
        output_format: Output format (GTiff, PNG, etc.)
        burn_value: Pixel value to burn for features
        crs: Target CRS (e.g., 'EPSG:4326')
        resolution: Output pixel size in map units (default 0.0001°)
        **kwargs: attribute (str) – field name to use for burn values

    Returns:
        Path to output file
    """
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize as rio_rasterize
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS as RasterioCRS

    driver_map = {"GTiff": "GTiff", "GeoTIFF": "GTiff", "PNG": "PNG",
                  "JPEG": "JPEG", "JPG": "JPEG", "GPKG": "GPKG"}
    rasterio_driver = driver_map.get(output_format, output_format)

    print(f"[rasterio] Rasterizing: {input_path} → {output_path}")

    gdf = gpd.read_file(input_path)
    if crs:
        gdf = gdf.to_crs(crs) if gdf.crs else gdf.set_crs(crs)

    minx, miny, maxx, maxy = gdf.total_bounds
    pixel_size = resolution if resolution else 0.0001
    width = min(8192, max(1, int((maxx - minx) / pixel_size)))
    height = min(8192, max(1, int((maxy - miny) / pixel_size)))

    transform = from_bounds(minx, miny, maxx, maxy, width, height)

    attribute = kwargs.get("attribute")
    if attribute and attribute in gdf.columns:
        shapes_iter = ((geom.__geo_interface__, float(val))
                       for geom, val in zip(gdf.geometry, gdf[attribute])
                       if geom is not None)
    else:
        shapes_iter = ((geom.__geo_interface__, burn_value)
                       for geom in gdf.geometry if geom is not None)

    burned = rio_rasterize(shapes_iter, out_shape=(height, width),
                           transform=transform, fill=0, dtype="uint8")

    raster_crs = RasterioCRS.from_string(crs) if crs else RasterioCRS.from_epsg(4326)
    profile = {"driver": rasterio_driver, "dtype": "uint8",
               "width": width, "height": height, "count": 1,
               "crs": raster_crs, "transform": transform}

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(burned, 1)

    print(f"[OK] Rasterized: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Raster → Vector  (replaces gdal_polygonize)
# ---------------------------------------------------------------------------

def raster_to_vector(input_path: str, output_path: str, output_format: str = "GeoJSON",
                     band: int = 1, crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert raster to vector using rasterio.features.shapes (polygonize).

    Args:
        input_path: Path to input raster file
        output_path: Path to output vector file
        output_format: OGR driver name (GeoJSON, ESRI Shapefile, GPKG, …)
        band: Band number to polygonize (default 1)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: field_name (str) – attribute name for raster values (default 'DN')

    Returns:
        Path to output file
    """
    import rasterio
    from rasterio.features import shapes as rio_shapes
    import geopandas as gpd

    print(f"[rasterio] Polygonizing: {input_path} → {output_path}")

    with rasterio.open(input_path) as src:
        data = src.read(band)
        mask = (data != src.nodata).astype("uint8") if src.nodata is not None else None
        src_crs = str(src.crs) if src.crs else "EPSG:4326"
        transform = src.transform

    field_name = kwargs.get("field_name", "DN")
    geoms = [
        {"geometry": geom, "properties": {field_name: int(val)}}
        for geom, val in rio_shapes(data.astype("float32"), mask=mask, transform=transform)
        if val != 0
    ]

    if not geoms:
        raise RuntimeError(f"No shapes were extracted from {input_path}. "
                           "All pixels may be nodata or zero.")

    gdf = gpd.GeoDataFrame.from_features(geoms, crs=src_crs)

    if crs and gdf.crs is not None:
        gdf = gdf.to_crs(crs)

    driver_map = {"GeoPackage": "GPKG", "KMZ": "LIBKML", "ESRI Shapefile": "ESRI Shapefile"}
    fiona_driver = driver_map.get(output_format, output_format)
    gdf.to_file(output_path, driver=fiona_driver)

    print(f"[OK] Polygonized: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def batch_convert_gdal_cli(input_path: str, output_path: str,
                            input_driver: str, input_driver_ext: str,
                            conversion_driver: str, conversion_driver_ext: str,
                            conversion_crs: Optional[str] = None,
                            **kwargs) -> List[str]:
    """
    Batch conversion using Python GDAL ecosystem (rasterio + geopandas).

    Args:
        input_path: Path to input file or directory
        output_path: Path to output directory
        input_driver: Input format driver name
        input_driver_ext: Input file extension (e.g. '.tif')
        conversion_driver: Output format driver name
        conversion_driver_ext: Output file extension
        conversion_crs: Target CRS for transformation
        **kwargs: Additional conversion options

    Returns:
        List of converted file paths
    """
    check_gdal_tools()

    # Find input files
    if os.path.isdir(input_path):
        files = []
        for root, _, filenames in os.walk(input_path):
            for f in filenames:
                if f.lower().endswith(input_driver_ext.lower()):
                    files.append(os.path.join(root, f))
    else:
        files = ([input_path]
                 if input_path.lower().endswith(input_driver_ext.lower())
                 else [])

    if not files:
        return []

    os.makedirs(output_path, exist_ok=True)

    raster_formats = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".gtiff"}
    input_is_raster = input_driver_ext.lower() in raster_formats
    output_is_raster = conversion_driver_ext.lower() in raster_formats

    converted_files = []
    for f in files:
        out_name = os.path.splitext(os.path.basename(f))[0] + conversion_driver_ext
        out_file = os.path.join(output_path, out_name)

        try:
            if input_is_raster and output_is_raster:
                raster_to_raster(f, out_file, conversion_driver, conversion_crs, **kwargs)
            elif not input_is_raster and not output_is_raster:
                vector_to_vector(f, out_file, conversion_driver, conversion_crs, **kwargs)
            elif not input_is_raster and output_is_raster:
                vector_to_raster(f, out_file, conversion_driver, crs=conversion_crs, **kwargs)
            elif input_is_raster and not output_is_raster:
                raster_to_vector(f, out_file, conversion_driver, crs=conversion_crs, **kwargs)
            converted_files.append(out_file)
        except Exception as e:
            print(f"[ERROR] Failed to convert {f}: {e}")

    return converted_files


# ---------------------------------------------------------------------------
# Format mappings
# ---------------------------------------------------------------------------

GDAL_RASTER_FORMATS = {
    "GTiff": "GTiff", "GeoTIFF": "GTiff",
    "PNG": "PNG", "JPEG": "JPEG", "JPG": "JPEG",
}

OGR_VECTOR_FORMATS = {
    "ESRI Shapefile": "ESRI Shapefile",
    "GeoJSON": "GeoJSON",
    "GeoPackage": "GPKG",
    "KML": "KML",
    "KMZ": "LIBKML",
    "OpenFileGDB": "OpenFileGDB",
    "DXF": "DXF",
    "CSV": "CSV",
    "FlatGeobuf": "FlatGeobuf",
    "GeoParquet": "Parquet",
    "GML": "GML",
    "Avro": "Avro",
    "Arrow IPC": "Arrow",
}


if __name__ == "__main__":
    print("GDAL/OGR Python-API Conversion Module")
    print("=" * 50)
    try:
        check_gdal_tools()
        print("✓ All required Python packages are available")
    except RuntimeError as e:
        print(f"✗ Error: {e}")
