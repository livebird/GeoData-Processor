"""
GDAL/OGR Command-Line Tool Conversion Module

This module implements geospatial data conversions using GDAL/OGR command-line tools
(gdal_translate, ogr2ogr, gdal_rasterize, gdal_polygonize) instead of Python wrappers.

Tools used:
- gdal_translate: Raster to raster conversion
- ogr2ogr: Vector to vector conversion
- gdal_rasterize: Vector to raster conversion
- gdal_polygonize: Raster to vector conversion
"""

import os
import subprocess
import shutil
from typing import List, Optional


def check_gdal_tools():
    """Check if GDAL tools are available in the system PATH."""
    tools = ['gdal_translate', 'ogr2ogr', 'gdal_rasterize', 'gdal_polygonize']
    missing = []
    for tool in tools:
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        raise RuntimeError(f"GDAL tools not found: {', '.join(missing)}. "
                         "Please install GDAL and ensure it's in your PATH.")
    return True


def raster_to_raster(input_path: str, output_path: str, output_format: str = 'GTiff',
                     crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert raster to raster using gdal_translate.
    
    Args:
        input_path: Path to input raster file
        output_path: Path to output raster file
        output_format: Output format (GTiff, PNG, JPEG, etc.)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: Additional gdal_translate options
    
    Returns:
        Path to output file
    """
    cmd = ['gdal_translate']
    
    # Set output format
    cmd.extend(['-of', output_format])
    
    # CRS transformation
    if crs:
        cmd.extend(['-a_srs', crs])
    
    # Additional options
    if kwargs.get('nodata'):
        cmd.extend(['-a_nodata', str(kwargs['nodata'])])
    
    if kwargs.get('scale'):
        scale = kwargs['scale']
        cmd.extend(['-scale', str(scale[0]), str(scale[1])])
    
    if kwargs.get('outsize'):
        outsize = kwargs['outsize']
        cmd.extend(['-outsize', str(outsize[0]), str(outsize[1])])
    
    # Input and output files
    cmd.extend([input_path, output_path])
    
    print(f"[GDAL] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"gdal_translate failed: {result.stderr}")
    
    print(f"[OK] Converted: {output_path}")
    return output_path


def vector_to_vector(input_path: str, output_path: str, output_format: str = 'GeoJSON',
                     crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert vector to vector using ogr2ogr.
    
    Args:
        input_path: Path to input vector file
        output_path: Path to output vector file
        output_format: Output format (ESRI Shapefile, GeoJSON, GeoPackage, etc.)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: Additional ogr2ogr options
    
    Returns:
        Path to output file
    """
    cmd = ['ogr2ogr']
    
    # Overwrite output file if exists
    cmd.append('-overwrite')
    
    # Set output format
    cmd.extend(['-f', output_format])
    
    # CRS transformation
    if crs:
        cmd.extend(['-t_srs', crs])
    
    # Layer options
    if kwargs.get('layer_name'):
        cmd.extend(['-nln', kwargs['layer_name']])
    
    # Geometry type filter
    if kwargs.get('geometry_type'):
        cmd.extend(['-nlt', kwargs['geometry_type']])
    
    # Skip failures
    if kwargs.get('skip_failures'):
        cmd.append('-skipfailures')
    
    # Input and output files
    cmd.extend([output_path, input_path])
    
    print(f"[OGR] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"ogr2ogr failed: {result.stderr}")
    
    print(f"[OK] Converted: {output_path}")
    return output_path


def vector_to_raster(input_path: str, output_path: str, output_format: str = 'GTiff',
                     burn_value: int = 255, crs: Optional[str] = None,
                     resolution: Optional[float] = None, **kwargs) -> str:
    """
    Convert vector to raster using gdal_rasterize.
    
    Args:
        input_path: Path to input vector file
        output_path: Path to output raster file
        output_format: Output format (GTiff, PNG, etc.)
        burn_value: Value to burn into raster pixels
        crs: Target CRS (e.g., 'EPSG:4326')
        resolution: Output resolution in map units
        **kwargs: Additional gdal_rasterize options
    
    Returns:
        Path to output file
    """
    cmd = ['gdal_rasterize']
    
    # Burn value
    cmd.extend(['-burn', str(burn_value)])
    
    # CRS transformation
    if crs:
        cmd.extend(['-a_srs', crs])
    
    # Resolution
    if resolution:
        cmd.extend(['-tr', str(resolution), str(resolution)])
    else:
        # Default resolution if not specified
        cmd.extend(['-tr', '1', '1'])
    
    # Output format
    cmd.extend(['-of', output_format])
    
    # Attribute to burn (optional)
    if kwargs.get('attribute'):
        cmd.extend(['-a', kwargs['attribute']])
    
    # All touched option
    if kwargs.get('all_touched'):
        cmd.append('-at')
    
    # Input and output files
    cmd.extend([input_path, output_path])
    
    print(f"[GDAL] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"gdal_rasterize failed: {result.stderr}")
    
    print(f"[OK] Converted: {output_path}")
    return output_path


def raster_to_vector(input_path: str, output_path: str, output_format: str = 'GeoJSON',
                     band: int = 1, crs: Optional[str] = None, **kwargs) -> str:
    """
    Convert raster to vector using gdal_polygonize.
    
    Args:
        input_path: Path to input raster file
        output_path: Path to output vector file
        output_format: Output format (ESRI Shapefile, GeoJSON, etc.)
        band: Band number to polygonize (default: 1)
        crs: Target CRS (e.g., 'EPSG:4326')
        **kwargs: Additional gdal_polygonize options
    
    Returns:
        Path to output file
    """
    cmd = ['gdal_polygonize.py']
    
    # Band to process
    cmd.extend([input_path, '-b', str(band)])
    
    # Output format
    cmd.extend(['-f', output_format])
    
    # Field name for raster values
    field_name = kwargs.get('field_name', 'DN')
    cmd.extend([output_path, field_name])
    
    print(f"[GDAL] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"gdal_polygonize failed: {result.stderr}")
    
    # Apply CRS transformation if needed
    if crs:
        vector_to_vector(output_path, output_path, output_format, crs)
    
    print(f"[OK] Converted: {output_path}")
    return output_path


def batch_convert_gdal_cli(input_path: str, output_path: str, 
                            input_driver: str, input_driver_ext: str,
                            conversion_driver: str, conversion_driver_ext: str,
                            conversion_crs: Optional[str] = None,
                            **kwargs) -> List[str]:
    """
    Batch conversion using GDAL/OGR command-line tools.
    
    Args:
        input_path: Path to input file or directory
        output_path: Path to output directory
        input_driver: Input format driver name
        input_driver_ext: Input file extension
        conversion_driver: Output format driver name
        conversion_driver_ext: Output file extension
        conversion_crs: Target CRS for transformation
        **kwargs: Additional conversion options
    
    Returns:
        List of converted file paths
    """
    # Check GDAL tools availability
    check_gdal_tools()
    
    # Find input files
    if os.path.isdir(input_path):
        files = []
        for root, _, filenames in os.walk(input_path):
            for f in filenames:
                if f.lower().endswith(input_driver_ext.lower()):
                    files.append(os.path.join(root, f))
    else:
        files = [input_path] if input_path.lower().endswith(input_driver_ext.lower()) else []
    
    if not files:
        return []
    
    # Create output directory
    os.makedirs(output_path, exist_ok=True)
    
    # Determine conversion type
    raster_formats = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.gtiff'}
    input_is_raster = input_driver_ext.lower() in raster_formats
    output_is_raster = conversion_driver_ext.lower() in raster_formats
    
    # Convert files
    converted_files = []
    for f in files:
        out_name = os.path.splitext(os.path.basename(f))[0] + conversion_driver_ext
        out_file = os.path.join(output_path, out_name)
        
        try:
            if input_is_raster and output_is_raster:
                # Raster to Raster
                raster_to_raster(f, out_file, conversion_driver, conversion_crs, **kwargs)
            elif not input_is_raster and not output_is_raster:
                # Vector to Vector
                vector_to_vector(f, out_file, conversion_driver, conversion_crs, **kwargs)
            elif not input_is_raster and output_is_raster:
                # Vector to Raster
                vector_to_raster(f, out_file, conversion_driver, crs=conversion_crs, **kwargs)
            elif input_is_raster and not output_is_raster:
                # Raster to Vector
                raster_to_vector(f, out_file, conversion_driver, crs=conversion_crs, **kwargs)
            
            converted_files.append(out_file)
        except Exception as e:
            print(f"[ERROR] Failed to convert {f}: {e}")
    
    return converted_files


# Format mappings for GDAL/OGR
GDAL_RASTER_FORMATS = {
    'GTiff': 'GTiff',
    'GeoTIFF': 'GTiff',
    'PNG': 'PNG',
    'JPEG': 'JPEG',
    'JPG': 'JPEG',
}

OGR_VECTOR_FORMATS = {
    'ESRI Shapefile': 'ESRI Shapefile',
    'GeoJSON': 'GeoJSON',
    'GeoPackage': 'GPKG',
    'KML': 'KML',
    'KMZ': 'LIBKML',
    'OpenFileGDB': 'OpenFileGDB',
    'DXF': 'DXF',
    'CSV': 'CSV',
    'FlatGeobuf': 'FlatGeobuf',
    'GeoParquet': 'Parquet',
    'GML': 'GML',
    'Avro': 'Avro',
    'Arrow IPC': 'Arrow',
}


if __name__ == '__main__':
    # Example usage
    print("GDAL/OGR Command-Line Conversion Module")
    print("=" * 50)
    
    try:
        check_gdal_tools()
        print("✓ All GDAL tools are available")
    except RuntimeError as e:
        print(f"✗ Error: {e}")
