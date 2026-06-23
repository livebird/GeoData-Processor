"""
Metadata extraction service for GDAL operations.

This module provides framework-agnostic metadata extraction from geospatial files
using ogrinfo -json as specified in SRS §7.2. It can be called by both Django REST
Framework views and Celery tasks.
"""

import os
import subprocess
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from .error_catalog import ErrorCatalog, ErrorCode, ErrorDetail


@dataclass
class LayerMetadata:
    """Metadata for a single layer in a vector dataset from ogrinfo -json."""
    name: str
    feature_count: int
    geometry_type: str
    fields: List[Dict[str, Any]]
    extent: Optional[Dict[str, float]] = None
    srs: Optional[str] = None
    srs_wkt: Optional[str] = None
    srs_epsg: Optional[int] = None
    encoding: Optional[str] = None
    has_z: bool = False
    has_m: bool = False
    mixed_geometry: bool = False
    geometry_types: Optional[List[str]] = None


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
    
    This service uses ogrinfo -json as specified in SRS §7.2 to extract comprehensive
    metadata from both vector and raster geospatial files. It can be used by Django
    views, Celery tasks, or any other framework without coupling to web-specific components.
    """
    
    @staticmethod
    def _run_ogrinfo(file_path: str, extra_args: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run ogrinfo -json command and return parsed JSON output.
        
        Args:
            file_path: Path to the geospatial file
            extra_args: Additional arguments for ogrinfo
            
        Returns:
            Parsed JSON output from ogrinfo
            
        Raises:
            subprocess.CalledProcessError: If ogrinfo fails
            json.JSONDecodeError: If output is not valid JSON
        """
        cmd = ["ogrinfo", "-json", file_path]
        if extra_args:
            cmd.extend(extra_args)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        return json.loads(result.stdout)
    
    @staticmethod
    def _run_gdalinfo(file_path: str, extra_args: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run gdalinfo -json command and return parsed JSON output.
        
        Args:
            file_path: Path to the raster file
            extra_args: Additional arguments for gdalinfo
            
        Returns:
            Parsed JSON output from gdalinfo
            
        Raises:
            subprocess.CalledProcessError: If gdalinfo fails
            json.JSONDecodeError: If output is not valid JSON
        """
        cmd = ["gdalinfo", "-json", file_path]
        if extra_args:
            cmd.extend(extra_args)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        return json.loads(result.stdout)
    
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
        Extract complete metadata from a geospatial file using ogrinfo/gdalinfo -json.
        
        Args:
            file_path: Path to the geospatial file
            
        Returns:
            FileMetadata object with complete metadata
            
        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: If metadata extraction fails
        """
        file_info = MetadataService.get_file_info(file_path)
        
        # Try ogrinfo first (vector files)
        try:
            ogrinfo_data = MetadataService._run_ogrinfo(file_path)
            
            # Parse ogrinfo output
            driver_name = ogrinfo_data.get("driverShortName", "unknown")
            driver_desc = ogrinfo_data.get("driverLongName", "unknown")
            
            # Extract layer metadata
            layers = ogrinfo_data.get("layers", [])
            layer_metadata = MetadataService._parse_ogrinfo_layers(layers)
            
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
            
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            # Try gdalinfo for raster files
            try:
                gdalinfo_data = MetadataService._run_gdalinfo(file_path)
                
                # Parse gdalinfo output
                driver_name = gdalinfo_data.get("driverShortName", "unknown")
                driver_desc = gdalinfo_data.get("driverLongName", "unknown")
                
                raster_metadata = MetadataService._parse_gdalinfo_raster(gdalinfo_data)
                
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
                
            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                error_detail = ErrorCatalog.get_error(
                    ErrorCode.FILE_CORRUPTED,
                    technical_message=f"ogrinfo/gdalinfo could not process file: {file_path}"
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
    
    @staticmethod
    def _parse_ogrinfo_layers(layers: List[Dict[str, Any]]) -> List[LayerMetadata]:
        """
        Parse layer metadata from ogrinfo -json output.
        
        Args:
            layers: List of layer objects from ogrinfo
            
        Returns:
            List of LayerMetadata objects
        """
        layer_metadata_list = []
        
        for layer_data in layers:
            # Extract field information
            fields = []
            for field in layer_data.get("fields", []):
                fields.append({
                    "name": field.get("name"),
                    "type": field.get("type"),
                    "width": field.get("width"),
                    "precision": field.get("precision"),
                })
            
            # Extract extent
            extent = None
            extent_data = layer_data.get("extent")
            if extent_data:
                extent = {
                    "x_min": extent_data.get("minx"),
                    "x_max": extent_data.get("maxx"),
                    "y_min": extent_data.get("miny"),
                    "y_max": extent_data.get("maxy"),
                }
            
            # Extract spatial reference
            srs = None
            srs_wkt = None
            srs_epsg = None
            srs_data = layer_data.get("srs")
            if srs_data:
                srs = srs_data.get("proj4")
                srs_wkt = srs_data.get("wkt")
                # Try to extract EPSG code from authority
                authority = srs_data.get("authority")
                if authority:
                    srs_epsg = authority.get("code")
            
            # Extract geometry type and detect Z/M dimensions
            geometry_type = layer_data.get("geometry", "Unknown")
            has_z = "Z" in geometry_type.upper()
            has_m = "M" in geometry_type.upper()
            
            # Detect mixed geometry types
            mixed_geometry = False
            geometry_types = [geometry_type]
            
            # ogrinfo may report multiple geometry types in some cases
            if "geometries" in layer_data:
                geom_list = layer_data.get("geometries", [])
                if geom_list and len(geom_list) > 1:
                    mixed_geometry = True
                    geometry_types = geom_list
            
            layer_metadata = LayerMetadata(
                name=layer_data.get("name", "unknown"),
                feature_count=layer_data.get("featureCount", 0),
                geometry_type=geometry_type,
                fields=fields,
                extent=extent,
                srs=srs,
                srs_wkt=srs_wkt,
                srs_epsg=srs_epsg,
                encoding=layer_data.get("encoding"),
                has_z=has_z,
                has_m=has_m,
                mixed_geometry=mixed_geometry,
                geometry_types=geometry_types if mixed_geometry else None,
            )
            
            layer_metadata_list.append(layer_metadata)
        
        return layer_metadata_list
    
    @staticmethod
    def _parse_gdalinfo_raster(gdalinfo_data: Dict[str, Any]) -> RasterMetadata:
        """
        Parse raster metadata from gdalinfo -json output.
        
        Args:
            gdalinfo_data: Dictionary from gdalinfo -json
            
        Returns:
            RasterMetadata object
        """
        # Get basic raster info
        size = gdalinfo_data.get("size", [0, 0])
        width = size[0]
        height = size[1]
        bands = gdalinfo_data.get("bands", [])
        band_count = len(bands)
        
        # Get data type from first band
        data_type = "Unknown"
        no_data_value = None
        if bands:
            data_type = bands[0].get("type", "Unknown")
            no_data_value = bands[0].get("noDataValue")
        
        # Get extent
        extent = {}
        extent_data = gdalinfo_data.get("wgs84Extent")
        if extent_data:
            extent = {
                "x_min": extent_data.get("minx"),
                "x_max": extent_data.get("maxx"),
                "y_min": extent_data.get("miny"),
                "y_max": extent_data.get("maxy"),
            }
        
        # Get spatial reference
        srs = None
        srs_wkt = None
        projection = None
        coordinate_system = gdalinfo_data.get("coordinateSystem")
        if coordinate_system:
            srs_wkt = coordinate_system.get("wkt")
            projection = coordinate_system.get("proj4")
            # Try to extract EPSG
            authority = coordinate_system.get("authority")
            if authority:
                srs = authority.get("code")
        
        # Get geo transform
        geo_transform = gdalinfo_data.get("geoTransform")
        
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
        Get list of layer names from a vector file using ogrinfo.
        
        Args:
            file_path: Path to the vector file
            
        Returns:
            List of layer names
        """
        try:
            ogrinfo_data = MetadataService._run_ogrinfo(file_path)
            layers = ogrinfo_data.get("layers", [])
            return [layer.get("name", "unknown") for layer in layers]
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return []
    
    @staticmethod
    def get_raster_band_info(file_path: str) -> List[Dict[str, Any]]:
        """
        Get information about raster bands using gdalinfo.
        
        Args:
            file_path: Path to the raster file
            
        Returns:
            List of band information dictionaries
        """
        try:
            gdalinfo_data = MetadataService._run_gdalinfo(file_path)
            bands = gdalinfo_data.get("bands", [])
            
            band_info = []
            for i, band in enumerate(bands, 1):
                band_info.append({
                    "band_number": i,
                    "data_type": band.get("type"),
                    "no_data_value": band.get("noDataValue"),
                    "color_interpretation": band.get("colorInterpretation"),
                    "block_size": band.get("block"),
                })
            
            return band_info
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return []
    
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
                    "srs_wkt": layer.srs_wkt,
                    "srs_epsg": layer.srs_epsg,
                    "encoding": layer.encoding,
                    "has_z": layer.has_z,
                    "has_m": layer.has_m,
                    "mixed_geometry": layer.mixed_geometry,
                    "geometry_types": layer.geometry_types,
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
                "srs_wkt": metadata.raster_metadata.srs_wkt,
                "geo_transform": metadata.raster_metadata.geo_transform,
                "projection": metadata.raster_metadata.projection,
            }
        
        return result
    
    @staticmethod
    def persist_to_geofilelayer(
        metadata: FileMetadata,
        geo_file: Any,
        update_existing: bool = True
    ) -> List[Any]:
        """
        Persist extracted metadata to GeoFileLayer model.
        
        This method creates or updates GeoFileLayer records with the extracted
        metadata from ogrinfo -json. This implements FR-MD-004 from SRS §7.2.
        
        Args:
            metadata: FileMetadata object with extracted metadata
            geo_file: GeoFile model instance to associate layers with
            update_existing: Whether to update existing layers or create new ones
            
        Returns:
            List of created/updated GeoFileLayer instances
            
        Raises:
            ImportError: If Django models are not available
            Exception: If persistence fails
        """
        try:
            from converter.models import GeoFileLayer
        except ImportError as e:
            raise ImportError(
                "Django models are not available. This method requires Django to be configured. "
                f"Error: {e}"
            )
        
        if not metadata.is_valid or not metadata.layer_metadata:
            return []
        
        created_layers = []
        
        for layer_meta in metadata.layer_metadata:
            # Prepare bbox in the format expected by GeoFileLayer
            bbox = layer_meta.extent if layer_meta.extent else {}
            
            # Prepare metadata JSON with additional fields
            layer_metadata_json = {
                "driver": metadata.driver,
                "driver_description": metadata.driver_description,
                "file_type": metadata.file_type,
                "mixed_geometry": layer_meta.mixed_geometry,
                "geometry_types": layer_meta.geometry_types,
                "srs": layer_meta.srs,
            }
            
            # Try to find existing layer by name and file
            existing_layer = None
            if update_existing:
                try:
                    existing_layer = GeoFileLayer.objects.filter(
                        file=geo_file,
                        layer_name=layer_meta.name
                    ).first()
                except Exception:
                    pass
            
            if existing_layer:
                # Update existing layer
                existing_layer.geometry_type = layer_meta.geometry_type
                existing_layer.has_z = layer_meta.has_z
                existing_layer.has_m = layer_meta.has_m
                existing_layer.source_crs_epsg = layer_meta.srs_epsg
                existing_layer.source_crs_wkt = layer_meta.srs_wkt
                existing_layer.feature_count = layer_meta.feature_count
                existing_layer.bbox = bbox
                existing_layer.fields = layer_meta.fields
                existing_layer.encoding = layer_meta.encoding or "UTF-8"
                existing_layer.metadata = layer_metadata_json
                existing_layer.save()
                created_layers.append(existing_layer)
            else:
                # Create new layer
                new_layer = GeoFileLayer.objects.create(
                    file=geo_file,
                    layer_name=layer_meta.name,
                    geometry_type=layer_meta.geometry_type,
                    has_z=layer_meta.has_z,
                    has_m=layer_meta.has_m,
                    source_crs_epsg=layer_meta.srs_epsg,
                    source_crs_wkt=layer_meta.srs_wkt,
                    feature_count=layer_meta.feature_count,
                    bbox=bbox,
                    fields=layer_meta.fields,
                    encoding=layer_meta.encoding or "UTF-8",
                    metadata=layer_metadata_json,
                )
                created_layers.append(new_layer)
        
        return created_layers
