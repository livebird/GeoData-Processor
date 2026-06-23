"""
Transformation service for GDAL format conversions.

This module provides framework-agnostic transformation logic for converting
between different geospatial file formats. It can be called by both Django
REST Framework views and Celery tasks.
"""

import os
import sys
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

try:
    import pyproj
    proj_data = pyproj.datadir.get_data_dir()
    os.environ['PROJ_LIB'] = proj_data
    os.environ['PROJ_DATA'] = proj_data
except ImportError:
    pass

try:
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize, shapes as r_shapes
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from shapely.geometry import shape as s_shape
    from fiona.drvsupport import supported_drivers
    
    # Enable more drivers in fiona
    supported_drivers['KML'] = 'rw'
    supported_drivers['LIBKML'] = 'rw'
    supported_drivers['DXF'] = 'rw'
    supported_drivers['GPKG'] = 'rw'
    supported_drivers['GML'] = 'rw'
    supported_drivers['Avro'] = 'rw'
    supported_drivers['Parquet'] = 'rw'
    supported_drivers['Arrow'] = 'rw'
    supported_drivers['GeoParquet'] = 'rw'
    supported_drivers['Arrow IPC'] = 'rw'
    supported_drivers['FlatGeobuf'] = 'rw'
except ImportError as e:
    print(f"Warning: Missing library: {e}")
    gpd = None
    rasterio = None

from .error_catalog import ErrorCatalog, ErrorCode
from .validation import ValidationService


# Raster format definitions
RASTER_FORMATS = {'GTiff': '.tif', 'PNG': '.png', 'JPEG': '.jpg', 'JPG': '.jpg', 'GPKG': '.gpkg'}


@dataclass
class TransformationResult:
    """Result of a transformation operation."""
    success: bool
    output_path: Optional[str] = None
    output_files: Optional[List[str]] = None
    error_message: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None


@dataclass
class TransformationOptions:
    """Options for transformation operations."""
    target_crs: Optional[str] = None
    preserve_fields: bool = True
    simplify_tolerance: Optional[float] = None
    raster_resolution: Optional[float] = None
    raster_band_count: int = 1
    raster_data_type: str = 'uint8'
    compress: bool = True
    create_zip: bool = True


class TransformationService:
    """
    Framework-agnostic service for geospatial format transformations.
    
    This service handles conversions between different geospatial file formats
    including vector-to-vector, raster-to-raster, vector-to-raster, and
    raster-to-vector transformations.
    """
    
    @staticmethod
    def _check_dependencies() -> None:
        """Check if required dependencies are available."""
        if gpd is None:
            raise ImportError(
                "geopandas is required for vector transformations. "
                "Install it using: pip install geopandas"
            )
        if rasterio is None:
            raise ImportError(
                "rasterio is required for raster transformations. "
                "Install it using: pip install rasterio"
            )
    
    @staticmethod
    def vector_to_vector(
        input_path: str,
        output_path: str,
        input_driver: str,
        output_driver: str,
        options: Optional[TransformationOptions] = None
    ) -> TransformationResult:
        """
        Convert vector file from one format to another.
        
        Args:
            input_path: Path to input vector file
            output_path: Path for output vector file
            input_driver: Input GDAL driver name
            output_driver: Output GDAL driver name
            options: Transformation options
            
        Returns:
            TransformationResult with operation status
        """
        TransformationService._check_dependencies()
        
        if options is None:
            options = TransformationOptions()
        
        start_time = datetime.now()
        
        try:
            # Read input file
            gdf = gpd.read_file(input_path, driver=input_driver)
            
            # Apply CRS transformation if specified
            if options.target_crs and gdf.crs is not None:
                gdf = gdf.to_crs(options.target_crs)
            
            # Simplify geometries if tolerance specified
            if options.simplify_tolerance is not None:
                gdf['geometry'] = gdf['geometry'].simplify(
                    tolerance=options.simplify_tolerance,
                    preserve_topology=True
                )
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Write output file
            gdf.to_file(output_path, driver=output_driver)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return TransformationResult(
                success=True,
                output_path=output_path,
                output_files=[output_path],
                metadata={
                    "input_driver": input_driver,
                    "output_driver": output_driver,
                    "feature_count": len(gdf),
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "fields": list(gdf.columns) if options.preserve_fields else [],
                },
                processing_time=processing_time,
            )
            
        except Exception as e:
            return TransformationResult(
                success=False,
                error_message=f"Vector to vector conversion failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "input_path": input_path,
                    "output_path": output_path,
                }
            )
    
    @staticmethod
    def raster_to_raster(
        input_path: str,
        output_path: str,
        input_driver: str,
        output_driver: str,
        options: Optional[TransformationOptions] = None
    ) -> TransformationResult:
        """
        Convert raster file from one format to another.
        
        Args:
            input_path: Path to input raster file
            output_path: Path for output raster file
            input_driver: Input GDAL driver name
            output_driver: Output GDAL driver name
            options: Transformation options
            
        Returns:
            TransformationResult with operation status
        """
        TransformationService._check_dependencies()
        
        if options is None:
            options = TransformationOptions()
        
        start_time = datetime.now()
        
        try:
            # Read input raster
            with rasterio.open(input_path) as src:
                profile = src.profile
                profile.update(driver=output_driver)
                
                # Update compression settings
                if options.compress and output_driver == 'GTiff':
                    profile.update(compress='DEFLATE', compresslevel=6)
                
                # Update resolution if specified
                if options.raster_resolution is not None:
                    transform = calculate_default_transform(
                        src.crs, src.crs, src.width, src.height,
                        *src.bounds, resolution=options.raster_resolution
                    )
                    profile.update(transform=transform)
                
                # Ensure output directory exists
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                # Write output raster
                with rasterio.open(output_path, 'w', **profile) as dst:
                    dst.write(src.read())
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return TransformationResult(
                success=True,
                output_path=output_path,
                output_files=[output_path],
                metadata={
                    "input_driver": input_driver,
                    "output_driver": output_driver,
                    "width": profile['width'],
                    "height": profile['height'],
                    "count": profile['count'],
                    "dtype": str(profile['dtype']),
                    "crs": str(profile['crs']),
                },
                processing_time=processing_time,
            )
            
        except Exception as e:
            return TransformationResult(
                success=False,
                error_message=f"Raster to raster conversion failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "input_path": input_path,
                    "output_path": output_path,
                }
            )
    
    @staticmethod
    def vector_to_raster(
        input_path: str,
        output_path: str,
        input_driver: str,
        output_driver: str,
        options: Optional[TransformationOptions] = None
    ) -> TransformationResult:
        """
        Convert vector file to raster format.
        
        Args:
            input_path: Path to input vector file
            output_path: Path for output raster file
            input_driver: Input GDAL driver name
            output_driver: Output GDAL driver name
            options: Transformation options
            
        Returns:
            TransformationResult with operation status
        """
        TransformationService._check_dependencies()
        
        if options is None:
            options = TransformationOptions()
        
        start_time = datetime.now()
        
        try:
            # Read input vector
            gdf = gpd.read_file(input_path, driver=input_driver)
            
            if gdf.empty:
                return TransformationResult(
                    success=False,
                    error_message="Input vector file contains no features",
                    error_detail={"input_path": input_path}
                )
            
            # Get raster dimensions from options or use defaults
            resolution = options.raster_resolution or 1.0
            bounds = gdf.total_bounds
            width = int((bounds[2] - bounds[0]) / resolution)
            height = int((bounds[3] - bounds[1]) / resolution)
            
            # Create transform
            from rasterio.transform import from_bounds
            transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)
            
            # Rasterize
            shapes = ((geom, 1) for geom in gdf.geometry)
            rasterized = rasterize(
                shapes,
                out_shape=(height, width),
                transform=transform,
                fill=0,
                dtype=options.raster_data_type,
                all_touched=True
            )
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Write output raster
            profile = {
                'driver': output_driver,
                'height': height,
                'width': width,
                'count': options.raster_band_count,
                'dtype': options.raster_data_type,
                'crs': gdf.crs,
                'transform': transform,
                'compress': 'DEFLATE' if options.compress else None,
            }
            
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(rasterized, 1)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return TransformationResult(
                success=True,
                output_path=output_path,
                output_files=[output_path],
                metadata={
                    "input_driver": input_driver,
                    "output_driver": output_driver,
                    "feature_count": len(gdf),
                    "width": width,
                    "height": height,
                    "resolution": resolution,
                    "crs": str(gdf.crs),
                },
                processing_time=processing_time,
            )
            
        except Exception as e:
            return TransformationResult(
                success=False,
                error_message=f"Vector to raster conversion failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "input_path": input_path,
                    "output_path": output_path,
                }
            )
    
    @staticmethod
    def raster_to_vector(
        input_path: str,
        output_path: str,
        input_driver: str,
        output_driver: str,
        options: Optional[TransformationOptions] = None
    ) -> TransformationResult:
        """
        Convert raster file to vector format.
        
        Args:
            input_path: Path to input raster file
            output_path: Path for output vector file
            input_driver: Input GDAL driver name
            output_driver: Output GDAL driver name
            options: Transformation options
            
        Returns:
            TransformationResult with operation status
        """
        TransformationService._check_dependencies()
        
        if options is None:
            options = TransformationOptions()
        
        start_time = datetime.now()
        
        try:
            # Read input raster
            with rasterio.open(input_path) as src:
                # Extract shapes from raster
                shapes = list(r_shapes(
                    src.read(1),
                    transform=src.transform
                ))
            
            if not shapes:
                return TransformationResult(
                    success=False,
                    error_message="No shapes found in raster",
                    error_detail={"input_path": input_path}
                )
            
            # Convert to GeoDataFrame
            geometries = [s_shape(geom) for geom, value in shapes]
            values = [value for geom, value in shapes]
            
            gdf = gpd.GeoDataFrame(
                {'value': values},
                geometry=geometries,
                crs=src.crs
            )
            
            # Apply CRS transformation if specified
            if options.target_crs and gdf.crs is not None:
                gdf = gdf.to_crs(options.target_crs)
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Write output vector
            gdf.to_file(output_path, driver=output_driver)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return TransformationResult(
                success=True,
                output_path=output_path,
                output_files=[output_path],
                metadata={
                    "input_driver": input_driver,
                    "output_driver": output_driver,
                    "feature_count": len(gdf),
                    "crs": str(gdf.crs),
                },
                processing_time=processing_time,
            )
            
        except Exception as e:
            return TransformationResult(
                success=False,
                error_message=f"Raster to vector conversion failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "input_path": input_path,
                    "output_path": output_path,
                }
            )
    
    @staticmethod
    def batch_convert(
        input_paths: List[str],
        output_dir: str,
        input_driver: str,
        output_driver: str,
        options: Optional[TransformationOptions] = None
    ) -> TransformationResult:
        """
        Convert multiple files in batch.
        
        Args:
            input_paths: List of input file paths
            output_dir: Directory for output files
            input_driver: Input GDAL driver name
            output_driver: Output GDAL driver name
            options: Transformation options
            
        Returns:
            TransformationResult with batch operation status
        """
        if options is None:
            options = TransformationOptions()
        
        output_files = []
        errors = []
        successful_conversions = 0
        
        for input_path in input_paths:
            try:
                # Generate output path
                file_name = os.path.splitext(os.path.basename(input_path))[0]
                ext = RASTER_FORMATS.get(output_driver, '.tif')
                output_path = os.path.join(output_dir, f"{file_name}{ext}")
                
                # Determine conversion type based on input driver
                if input_driver in ValidationService.get_supported_drivers("vector"):
                    if output_driver in ValidationService.get_supported_drivers("vector"):
                        result = TransformationService.vector_to_vector(
                            input_path, output_path, input_driver, output_driver, options
                        )
                    else:
                        result = TransformationService.vector_to_raster(
                            input_path, output_path, input_driver, output_driver, options
                        )
                else:
                    if output_driver in ValidationService.get_supported_drivers("raster"):
                        result = TransformationService.raster_to_raster(
                            input_path, output_path, input_driver, output_driver, options
                        )
                    else:
                        result = TransformationService.raster_to_vector(
                            input_path, output_path, input_driver, output_driver, options
                        )
                
                if result.success:
                    output_files.extend(result.output_files or [])
                    successful_conversions += 1
                else:
                    errors.append({
                        "input_path": input_path,
                        "error": result.error_message,
                    })
                    
            except Exception as e:
                errors.append({
                    "input_path": input_path,
                    "error": str(e),
                })
        
        return TransformationResult(
            success=len(errors) == 0,
            output_files=output_files,
            error_message=f"Batch conversion completed with {len(errors)} errors" if errors else None,
            error_detail={"errors": errors} if errors else None,
            metadata={
                "total_files": len(input_paths),
                "successful_conversions": successful_conversions,
                "failed_conversions": len(errors),
            },
        )
    
    @staticmethod
    def create_output_zip(output_files: List[str], zip_path: str) -> bool:
        """
        Create a ZIP archive containing output files.
        
        Args:
            output_files: List of file paths to include in the ZIP
            zip_path: Path for the output ZIP file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            os.makedirs(os.path.dirname(zip_path), exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in output_files:
                    if os.path.exists(file_path):
                        arcname = os.path.basename(file_path)
                        zipf.write(file_path, arcname)
            
            return True
        except Exception as e:
            print(f"Error creating ZIP: {e}")
            return False
