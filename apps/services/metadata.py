"""
Metadata extraction service for GDAL operations.

This module provides framework-agnostic metadata extraction from geospatial files
using GDAL. It can be called by both Django REST Framework views and Celery tasks.
"""

import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

try:
    from osgeo import gdal, ogr, osr
except ImportError:
    gdal = None
    ogr = None
    osr = None

from .error_catalog import ErrorCatalog, ErrorCode, ErrorDetail


@dataclass
class LayerMetadata:
    """Metadata for a single layer in a vector dataset."""
    name: str
    feature_count: int
    geometry_type: str
    fields: List[Dict[str, str]]
    extent: Optional[Dict[str, float]] = None
    srs: Optional[str] = None
    srs_wkt: Optional[str] = None


@dataclass
class RasterMetadata:
    """Metadata for a raster dataset."""
    width: int
    height: int
    band_count: int
    data_type: str
    no_data_value: Optional[float]
    extent: Dict[str, float]
    srs: Optional[str]
    srs_wkt: Optional[str]
    geo_transform: Optional[List[float]]
    projection: Optional[str]


@dataclass
class FileMetadata:
    """Complete metadata for a geospatial file."""
    file_path: str
    file_name: str
    file_size: int
    driver: str
    driver_description: str
    file_type: str  # 'vector' or 'raster'
    is_valid: bool
    error_message: Optional[str] = None
    layer_metadata: Optional[List[LayerMetadata]] = None
    raster_metadata: Optional[RasterMetadata] = None
    creation_time: Optional[str] = None
    modification_time: Optional[str] = None


class MetadataService:
    """
    Framework-agnostic service for extracting metadata from geospatial files.
    
    This service uses GDAL to extract comprehensive metadata from both vector
    and raster geospatial files. It can be used by Django views, Celery tasks,
    or any other framework without coupling to web-specific components.
    """
    
    @staticmethod
    def _check_gdal_available() -> None:
        """Check if GDAL is available and raise an error if not."""
        if gdal is None:
            raise ImportError(
                "GDAL is not installed. Please install it using: "
                "pip install gdal or conda install gdal"
            )
    
    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        """
        Get basic file information (size, timestamps, etc.).
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with file information
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        stat = os.stat(file_path)
        return {
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "file_size": stat.st_size,
            "creation_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modification_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    
    @staticmethod
    def extract_metadata(file_path: str) -> FileMetadata:
        """
        Extract complete metadata from a geospatial file.
        
        Args:
            file_path: Path to the geospatial file
            
        Returns:
            FileMetadata object with complete metadata
            
        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: If metadata extraction fails
        """
        MetadataService._check_gdal_available()
        
        file_info = MetadataService.get_file_info(file_path)
        
        # Open the dataset with GDAL
        dataset = gdal.Open(file_path, gdal.GA_ReadOnly)
        
        if dataset is None:
            error_detail = ErrorCatalog.get_error(
                ErrorCode.FILE_CORRUPTED,
                technical_message=f"GDAL could not open file: {file_path}"
            )
            return FileMetadata(
                file_path=file_info["file_path"],
                file_name=file_info["file_name"],
                file_size=file_info["file_size"],
                driver="unknown",
                driver_description="unknown",
                file_type="unknown",
                is_valid=False,
                error_message=error_detail.message,
                creation_time=file_info["creation_time"],
                modification_time=file_info["modification_time"],
            )
        
        driver = dataset.GetDriver()
        driver_name = driver.ShortName if driver else "unknown"
        driver_desc = driver.LongName if driver else "unknown"
        
        # Determine if it's a vector or raster dataset
        if dataset.GetLayerCount() > 0:
            # Vector dataset
            layer_metadata = MetadataService._extract_vector_metadata(dataset)
            return FileMetadata(
                file_path=file_info["file_path"],
                file_name=file_info["file_name"],
                file_size=file_info["file_size"],
                driver=driver_name,
                driver_description=driver_desc,
                file_type="vector",
                is_valid=True,
                layer_metadata=layer_metadata,
                creation_time=file_info["creation_time"],
                modification_time=file_info["modification_time"],
            )
        else:
            # Raster dataset
            raster_metadata = MetadataService._extract_raster_metadata(dataset)
            return FileMetadata(
                file_path=file_info["file_path"],
                file_name=file_info["file_name"],
                file_size=file_info["file_size"],
                driver=driver_name,
                driver_description=driver_desc,
                file_type="raster",
                is_valid=True,
                raster_metadata=raster_metadata,
                creation_time=file_info["creation_time"],
                modification_time=file_info["modification_time"],
            )
    
    @staticmethod
    def _extract_vector_metadata(dataset) -> List[LayerMetadata]:
        """
        Extract metadata from vector layers.
        
        Args:
            dataset: GDAL dataset
            
        Returns:
            List of LayerMetadata objects
        """
        layers = []
        layer_count = dataset.GetLayerCount()
        
        for i in range(layer_count):
            layer = dataset.GetLayerByIndex(i)
            if not layer:
                continue
            
            # Get layer definition
            layer_defn = layer.GetLayerDefn()
            
            # Get field definitions
            fields = []
            field_count = layer_defn.GetFieldCount()
            for j in range(field_count):
                field_defn = layer_defn.GetFieldDefn(j)
                fields.append({
                    "name": field_defn.GetName(),
                    "type": ogr.FieldType.Get(field_defn.GetType()),
                    "width": field_defn.GetWidth(),
                    "precision": field_defn.GetPrecision(),
                })
            
            # Get extent
            extent = None
            try:
                x_min, x_max, y_min, y_max = layer.GetExtent()
                extent = {
                    "x_min": x_min,
                    "x_max": x_max,
                    "y_min": y_min,
                    "y_max": y_max,
                }
            except Exception:
                pass
            
            # Get spatial reference
            srs = None
            srs_wkt = None
            try:
                spatial_ref = layer.GetSpatialRef()
                if spatial_ref:
                    srs = spatial_ref.GetAttrValue("AUTHORITY", 0)
                    srs_wkt = spatial_ref.ExportToWkt()
            except Exception:
                pass
            
            # Get geometry type
            geom_type = ogr.GeometryTypeToName(layer.GetGeomType())
            
            layers.append(LayerMetadata(
                name=layer.GetName(),
                feature_count=layer.GetFeatureCount(),
                geometry_type=geom_type,
                fields=fields,
                extent=extent,
                srs=srs,
                srs_wkt=srs_wkt,
            ))
        
        return layers
    
    @staticmethod
    def _extract_raster_metadata(dataset) -> RasterMetadata:
        """
        Extract metadata from raster datasets.
        
        Args:
            dataset: GDAL dataset
            
        Returns:
            RasterMetadata object
        """
        # Get basic raster info
        width = dataset.RasterXSize
        height = dataset.RasterYSize
        band_count = dataset.RasterCount
        
        # Get first band for data type and no data value
        band = dataset.GetRasterBand(1)
        data_type = gdal.GetDataTypeName(band.DataType)
        no_data_value = band.GetNoDataValue()
        
        # Get extent
        geo_transform = dataset.GetGeoTransform()
        extent = {}
        if geo_transform:
            extent = {
                "x_min": geo_transform[0],
                "y_max": geo_transform[3],
                "x_max": geo_transform[0] + geo_transform[1] * width,
                "y_min": geo_transform[3] + geo_transform[5] * height,
            }
        
        # Get spatial reference
        srs = None
        srs_wkt = None
        projection = None
        try:
            spatial_ref = osr.SpatialReference(dataset.GetProjection())
            if spatial_ref:
                srs = spatial_ref.GetAttrValue("AUTHORITY", 0)
                srs_wkt = spatial_ref.ExportToWkt()
                projection = dataset.GetProjection()
        except Exception:
            pass
        
        return RasterMetadata(
            width=width,
            height=height,
            band_count=band_count,
            data_type=data_type,
            no_data_value=no_data_value,
            extent=extent,
            srs=srs,
            srs_wkt=srs_wkt,
            geo_transform=geo_transform,
            projection=projection,
        )
    
    @staticmethod
    def get_layer_names(file_path: str) -> List[str]:
        """
        Get list of layer names from a vector file.
        
        Args:
            file_path: Path to the vector file
            
        Returns:
            List of layer names
        """
        MetadataService._check_gdal_available()
        
        dataset = gdal.OpenEx(file_path, gdal.OF_VECTOR)
        if not dataset:
            return []
        
        layer_names = []
        for i in range(dataset.GetLayerCount()):
            layer = dataset.GetLayerByIndex(i)
            if layer:
                layer_names.append(layer.GetName())
        
        return layer_names
    
    @staticmethod
    def get_raster_band_info(file_path: str) -> List[Dict[str, Any]]:
        """
        Get information about raster bands.
        
        Args:
            file_path: Path to the raster file
            
        Returns:
            List of band information dictionaries
        """
        MetadataService._check_gdal_available()
        
        dataset = gdal.Open(file_path, gdal.GA_ReadOnly)
        if not dataset:
            return []
        
        band_info = []
        for i in range(1, dataset.RasterCount() + 1):
            band = dataset.GetRasterBand(i)
            if band:
                band_info.append({
                    "band_number": i,
                    "data_type": gdal.GetDataTypeName(band.DataType),
                    "no_data_value": band.GetNoDataValue(),
                    "minimum": band.GetMinimum(),
                    "maximum": band.GetMaximum(),
                    "scale": band.GetScale(),
                    "offset": band.GetOffset(),
                })
        
        return band_info
    
    @staticmethod
    def metadata_to_dict(metadata: FileMetadata) -> Dict[str, Any]:
        """
        Convert FileMetadata object to dictionary for API responses.
        
        Args:
            metadata: FileMetadata object
            
        Returns:
            Dictionary representation of metadata
        """
        result = {
            "file_path": metadata.file_path,
            "file_name": metadata.file_name,
            "file_size": metadata.file_size,
            "driver": metadata.driver,
            "driver_description": metadata.driver_description,
            "file_type": metadata.file_type,
            "is_valid": metadata.is_valid,
            "creation_time": metadata.creation_time,
            "modification_time": metadata.modification_time,
        }
        
        if metadata.error_message:
            result["error_message"] = metadata.error_message
        
        if metadata.layer_metadata:
            result["layers"] = [
                {
                    "name": layer.name,
                    "feature_count": layer.feature_count,
                    "geometry_type": layer.geometry_type,
                    "fields": layer.fields,
                    "extent": layer.extent,
                    "srs": layer.srs,
                }
                for layer in metadata.layer_metadata
            ]
        
        if metadata.raster_metadata:
            result["raster"] = {
                "width": metadata.raster_metadata.width,
                "height": metadata.raster_metadata.height,
                "band_count": metadata.raster_metadata.band_count,
                "data_type": metadata.raster_metadata.data_type,
                "no_data_value": metadata.raster_metadata.no_data_value,
                "extent": metadata.raster_metadata.extent,
                "srs": metadata.raster_metadata.srs,
                "geo_transform": metadata.raster_metadata.geo_transform,
            }
        
        return result
