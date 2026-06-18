"""
Raster Spike Module (v1.0)
Handles GeoTIFF metadata extraction, reprojection, and Cloud Optimized GeoTIFF conversion.
"""

import os
import json
import warnings
from typing import Dict, List, Optional, Tuple

# Fix PROJ database compatibility issues
# CRITICAL: Set PROJ paths BEFORE importing rasterio to avoid conflicting PROJ installations
os.environ['PROJ_IGNORE_ETW_PYTHON_ENVVAR'] = '1'  # Ignore environment detection
try:
    import pyproj
    from pyproj import CRS
    
    # Use pyproj's bundled proj data
    proj_data = pyproj.datadir.get_data_dir()
    
    # Clear any system PROJ paths to avoid conflicts
    os.environ.pop('PROJ_DATA', None)
    os.environ.pop('GDAL_DATA', None)
    
    # Set to pyproj's bundled data
    os.environ['PROJ_LIB'] = proj_data
    os.environ['PROJ_DATA'] = proj_data
    
    print(f"[PROJ] Using bundled data from: {proj_data}")
except Exception as e:
    print(f"Warning: Could not set PROJ paths: {e}")

try:
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.io import MemoryFile
    from rasterio.enums import Resampling as RasterioResampling
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class RasterMetadata:
    """Represents GeoTIFF metadata in user-friendly format."""
    
    def __init__(self, filepath: str):
        """Extract metadata from a raster file."""
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.metadata = {}
        self._extract_metadata()
    
    def _extract_metadata(self):
        """Extract technical metadata from raster file."""
        if not HAS_RASTERIO:
            raise RuntimeError("Rasterio is required for raster metadata extraction")
        
        try:
            with rasterio.open(self.filepath) as src:
                # Basic file information
                self.metadata['file_size_mb'] = round(os.path.getsize(self.filepath) / (1024 * 1024), 2)
                
                # Spatial information
                self.metadata['resolution'] = {
                    'x': round(src.transform.a, 6),  # Pixel width
                    'y': round(abs(src.transform.e), 6),  # Pixel height
                    'unit': 'degrees' if src.crs and 'degrees' in str(src.crs).lower() else 'meters'
                }
                
                # Coordinate Reference System
                self.metadata['crs'] = {
                    'epsg': src.crs.to_epsg() if src.crs else None,
                    'wkt': str(src.crs) if src.crs else None,
                    'proj4': src.crs.to_proj4() if src.crs else None
                }
                
                # Raster dimensions
                self.metadata['dimensions'] = {
                    'width': src.width,
                    'height': src.height,
                    'pixel_count': src.width * src.height
                }
                
                # Band information
                self.metadata['bands'] = []
                for i in range(1, src.count + 1):
                    band = src.read(i)
                    band_info = {
                        'number': i,
                        'dtype': str(band.dtype),
                        'no_data': src.nodata,
                        'min': float(np.min(band[band != src.nodata])) if HAS_NUMPY else None,
                        'max': float(np.max(band[band != src.nodata])) if HAS_NUMPY else None,
                    }
                    self.metadata['bands'].append(band_info)
                
                # Geospatial extent (bounds)
                bounds = src.bounds
                self.metadata['extent'] = {
                    'min_x': round(bounds.left, 6),
                    'min_y': round(bounds.bottom, 6),
                    'max_x': round(bounds.right, 6),
                    'max_y': round(bounds.top, 6)
                }
                
                # Projection information (user-friendly)
                self.metadata['projection_info'] = {
                    'is_geographic': src.crs.is_geographic if src.crs else False,
                    'is_projected': src.crs.is_projected if src.crs else False,
                    'description': src.crs.to_string() if src.crs else 'Unknown'
                }
                
        except Exception as e:
            raise RuntimeError(f"Failed to extract metadata from {self.filepath}: {str(e)}")
    
    def to_dict(self) -> Dict:
        """Return metadata as dictionary."""
        return self.metadata
    
    def to_json(self) -> str:
        """Return metadata as JSON string."""
        return json.dumps(self.metadata, indent=2, default=str)
    
    def get_user_friendly_summary(self) -> Dict:
        """Return metadata in user-friendly format with explanations."""
        meta = self.metadata
        return {
            'File Information': {
                'Name': self.filename,
                'Size': f"{meta['file_size_mb']} MB"
            },
            'Map Details': {
                'Resolution': f"{meta['resolution']['x']} x {meta['resolution']['y']} {meta['resolution']['unit']}",
                'Dimensions': f"{meta['dimensions']['width']} x {meta['dimensions']['height']} pixels",
                'Total Pixels': f"{meta['dimensions']['pixel_count']:,}"
            },
            'Coordinate System': {
                'EPSG Code': meta['crs']['epsg'] or 'Not specified',
                'Type': 'Geographic (Lat/Lon)' if meta['projection_info']['is_geographic'] else 'Projected',
                'Description': meta['projection_info']['description']
            },
            'Geographic Extent': {
                'West': f"{meta['extent']['min_x']}°",
                'South': f"{meta['extent']['min_y']}°",
                'East': f"{meta['extent']['max_x']}°",
                'North': f"{meta['extent']['max_y']}°",
            },
            'Data Bands': f"{len(meta['bands'])} band(s)"
        }


def get_raster_metadata(filepath: str) -> Dict:
    """
    Extract GeoTIFF metadata.
    
    Args:
        filepath: Path to raster file
    
    Returns:
        Dictionary with technical metadata
    """
    metadata = RasterMetadata(filepath)
    return metadata.to_dict()


def reproject_raster(input_path: str, output_path: str, target_crs: str, 
                     resampling_method: str = 'bilinear') -> str:
    """
    Reproject raster to a different coordinate system.
    
    Example:
        reproject_raster('input.tif', 'output.tif', 'EPSG:3857')
        # Converts from current CRS to Web Mercator (EPSG:3857)
    
    Args:
        input_path: Path to input raster file
        output_path: Path to output reprojected file
        target_crs: Target CRS (e.g., 'EPSG:3857', 'EPSG:4326')
        resampling_method: Resampling method ('nearest', 'bilinear', 'cubic', 'lanczos')
    
    Returns:
        Path to output file
    """
    if not HAS_RASTERIO:
        raise RuntimeError("Rasterio is required for raster reprojection")
    
    # Map resampling method strings to rasterio enums
    resampling_map = {
        'nearest': Resampling.nearest,
        'bilinear': Resampling.bilinear,
        'cubic': Resampling.cubic,
        'lanczos': Resampling.lanczos
    }
    
    resampling = resampling_map.get(resampling_method.lower(), Resampling.bilinear)
    
    try:
        # Force reinit of PROJ paths before any CRS operations
        try:
            import pyproj.datadir
            pyproj.datadir.set_data_dir(pyproj.datadir.get_data_dir())
        except:
            pass
        
        # Validate target CRS by trying to parse it
        try:
            from pyproj import CRS
            
            # Try multiple CRS formats to handle PROJ database issues
            target_crs_obj = None
            crs_error = None
            
            # Try 1: Direct string parsing
            try:
                target_crs_obj = CRS.from_string(target_crs)
                print(f"[OK] Target CRS parsed: {target_crs}")
            except Exception as e1:
                crs_error = e1
                print(f"[WARN] CRS.from_string failed: {e1}")
                
                # Try 2: Extract EPSG code and use from_epsg()
                if 'EPSG:' in target_crs.upper():
                    try:
                        epsg_code = int(target_crs.split(':')[1])
                        target_crs_obj = CRS.from_epsg(epsg_code)
                        print(f"[OK] Target CRS parsed from EPSG code: {epsg_code}")
                    except Exception as e2:
                        crs_error = e2
                        print(f"[WARN] CRS.from_epsg failed: {e2}")
            
            if target_crs_obj is None:
                raise RuntimeError(f"Cannot parse target CRS '{target_crs}': {str(crs_error)}")
        
        except Exception as crs_err:
            raise RuntimeError(f"Invalid target CRS '{target_crs}': {str(crs_err)}")
        
        with rasterio.open(input_path) as src:
            # Validate source CRS
            src_crs = None
            if src.crs is None:
                print(f"[WARNING] Source file has no CRS. Assuming EPSG:4326")
                try:
                    src_crs = CRS.from_epsg(4326)
                except:
                    src_crs = None
            else:
                src_crs = src.crs
            
            if src_crs is None:
                raise RuntimeError("Cannot determine source CRS and EPSG:4326 lookup failed")
            
            # Calculate transform and dimensions for target CRS
            print(f"[INFO] Calculating transform from {src_crs} to {target_crs}")
            transform, width, height = calculate_default_transform(
                src_crs, target_crs_obj, src.width, src.height, *src.bounds
            )
            
            # Update profile for output
            profile = src.profile.copy()
            profile.update({
                'crs': target_crs_obj,
                'transform': transform,
                'width': width,
                'height': height
            })
            
            # Reproject and write
            print(f"[INFO] Writing reprojected raster to {output_path}")
            with rasterio.open(output_path, 'w', **profile) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        rasterio.band(src, i),
                        rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src_crs,
                        dst_transform=transform,
                        dst_crs=target_crs_obj,
                        resampling=resampling
                    )
        
        print(f"[OK] Reprojected: {os.path.basename(input_path)} → {target_crs}")
        return output_path
        
    except Exception as e:
        import traceback
        print(f"[ERROR] Reprojection error trace: {traceback.format_exc()}")
        raise RuntimeError(f"Reprojection failed for {input_path}: {str(e)}")


def convert_to_cog(input_path: str, output_path: str, compression: str = 'deflate') -> str:
    """
    Convert GeoTIFF to Cloud Optimized GeoTIFF (COG).
    
    Cloud Optimized GeoTIFFs are optimized for:
    - Faster cloud access (HTTP range requests)
    - Better streaming performance
    - Efficient partial reading
    
    Args:
        input_path: Path to input raster file
        output_path: Path to output COG file
        compression: Compression method ('deflate', 'lzw', 'zstd', 'none')
    
    Returns:
        Path to output COG file
    """
    if not HAS_RASTERIO:
        raise RuntimeError("Rasterio is required for COG conversion")
    
    try:
        with rasterio.open(input_path) as src:
            profile = src.profile.copy()
            
            # COG-specific settings
            profile.update({
                'driver': 'GTiff',
                'compress': compression,
                'TILED': 'YES',
                'BLOCKXSIZE': 512,
                'BLOCKYSIZE': 512,
                'COPY_SRC_OVERVIEWS': 'YES',
                'COMPRESS': compression.upper()
            })
            
            # Write COG
            with rasterio.open(output_path, 'w', **profile) as dst:
                for i in range(1, src.count + 1):
                    data = src.read(i)
                    dst.write(data, i)
        
        print(f"[OK] Converted to COG: {os.path.basename(input_path)}")
        return output_path
        
    except Exception as e:
        raise RuntimeError(f"COG conversion failed for {input_path}: {str(e)}")


def batch_reproject_rasters(input_files: List[str], output_dir: str, 
                           target_crs: str, ext: str = '.tif') -> List[str]:
    """
    Reproject multiple raster files.
    
    Args:
        input_files: List of input raster file paths
        output_dir: Output directory for reprojected files
        target_crs: Target CRS (e.g., 'EPSG:3857')
        ext: Output file extension
    
    Returns:
        List of output file paths
    """
    reprojected = []
    for input_file in input_files:
        try:
            if not os.path.exists(input_file):
                print(f"[ERROR] File not found: {input_file}")
                continue
            
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + ext
            output_path = os.path.join(output_dir, output_filename)
            
            reproject_raster(input_file, output_path, target_crs)
            reprojected.append(output_path)
            
        except Exception as e:
            print(f"[ERROR] Failed to reproject {input_file}: {str(e)}")
    
    return reprojected


def batch_convert_to_cog(input_files: List[str], output_dir: str, 
                        compression: str = 'deflate') -> List[str]:
    """
    Convert multiple raster files to Cloud Optimized GeoTIFFs.
    
    Args:
        input_files: List of input raster file paths
        output_dir: Output directory for COG files
        compression: Compression method
    
    Returns:
        List of output COG file paths
    """
    converted = []
    for input_file in input_files:
        try:
            if not os.path.exists(input_file):
                print(f"[ERROR] File not found: {input_file}")
                continue
            
            output_filename = os.path.splitext(os.path.basename(input_file))[0] + '_cog.tif'
            output_path = os.path.join(output_dir, output_filename)
            
            convert_to_cog(input_file, output_path, compression)
            converted.append(output_path)
            
        except Exception as e:
            print(f"[ERROR] Failed to convert {input_file} to COG: {str(e)}")
    
    return converted
