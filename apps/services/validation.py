"""
Validation service for GDAL operations.

This module provides framework-agnostic validation for geospatial files,
conversion pairs, and input parameters. It can be called by both Django REST
Framework views and Celery tasks.
"""

import os
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from .metadata import MetadataService, FileMetadata
from .error_catalog import ErrorCatalog, ErrorCode, ErrorDetail


# Supported GDAL drivers and their extensions
VECTOR_DRIVERS = {
    "ESRI Shapefile": [".shp"],
    "GeoJSON": [".geojson", ".json"],
    "GPKG": [".gpkg"],
    "KML": [".kml"],
    "KMZ": [".kmz"],
    "GeoPackage": [".gpkg"],
    "CSV": [".csv"],
    "DXF": [".dxf"],
    "DGN": [".dgn"],
    "FileGDB": [".gdb"],
    "OpenFileGDB": [".gdb"],
    "PostgreSQL": [],  # Database, no extension
    "MSSQLSpatial": [],  # Database, no extension
}

RASTER_DRIVERS = {
    "GTiff": [".tif", ".tiff"],
    "PNG": [".png"],
    "JPEG": [".jpg", ".jpeg"],
    "BMP": [".bmp"],
    "GIF": [".gif"],
    "IMG": [".img"],
    "EHdr": [".hdr"],
    "AAIGrid": [".asc"],
    "DEM": [".dem"],
    "VRT": [".vrt"],
    "NITF": [".ntf", ".nitf"],
    "ECW": [".ecw"],
    "JP2OpenJPEG": [".jp2"],
    "MRF": [".mrf"],
}

# Supported conversion pairs (input_driver -> output_driver)
SUPPORTED_CONVERSIONS = {
    # Vector to Vector
    ("ESRI Shapefile", "GeoJSON"): True,
    ("ESRI Shapefile", "GPKG"): True,
    ("ESRI Shapefile", "KML"): True,
    ("GeoJSON", "ESRI Shapefile"): True,
    ("GeoJSON", "GPKG"): True,
    ("GeoJSON", "KML"): True,
    ("GPKG", "ESRI Shapefile"): True,
    ("GPKG", "GeoJSON"): True,
    ("GPKG", "KML"): True,
    ("KML", "ESRI Shapefile"): True,
    ("KML", "GeoJSON"): True,
    ("KML", "GPKG"): True,
    
    # Raster to Raster
    ("GTiff", "PNG"): True,
    ("GTiff", "JPEG"): True,
    ("GTiff", "BMP"): True,
    ("GTiff", "VRT"): True,
    ("PNG", "GTiff"): True,
    ("JPEG", "GTiff"): True,
    ("BMP", "GTiff"): True,
    ("IMG", "GTiff"): True,
    ("EHdr", "GTiff"): True,
    ("AAIGrid", "GTiff"): True,
    
    # Vector to Raster
    ("ESRI Shapefile", "GTiff"): True,
    ("GeoJSON", "GTiff"): True,
    ("GPKG", "GTiff"): True,
    ("KML", "GTiff"): True,
    
    # Raster to Vector
    ("GTiff", "ESRI Shapefile"): True,
    ("GTiff", "GeoJSON"): True,
    ("GTiff", "GPKG"): True,
}


@dataclass
class ValidationResult:
    """Result of a validation operation."""
    valid: bool
    reason: Optional[str] = None
    hint: Optional[str] = None
    error_detail: Optional[ErrorDetail] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class ConversionPairValidation:
    """Result of conversion pair validation."""
    valid: bool
    reason: Optional[str] = None
    supported_conversions: Optional[List[Tuple[str, str]]] = None


class ValidationService:
    """
    Framework-agnostic service for validating geospatial files and operations.
    
    This service provides validation for:
    - File existence and accessibility
    - File format and driver compatibility
    - Conversion pair support
    - Input parameters
    - CRS/coordinate system validity
    """
    
    @staticmethod
    def validate_file_exists(file_path: str) -> ValidationResult:
        """
        Validate that a file exists and is accessible.
        
        Args:
            file_path: Path to the file
            
        Returns:
            ValidationResult with validation status
        """
        if not file_path:
            return ValidationResult(
                valid=False,
                reason="File path is empty",
                hint="Provide a valid file path",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.FILE_NOT_FOUND,
                    context={"file_path": file_path}
                )
            )
        
        if not os.path.exists(file_path):
            return ValidationResult(
                valid=False,
                reason=f"File does not exist: {file_path}",
                hint="Verify the file path and ensure the file exists",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.FILE_NOT_FOUND,
                    context={"file_path": file_path}
                )
            )
        
        if not os.path.isfile(file_path):
            return ValidationResult(
                valid=False,
                reason=f"Path is not a file: {file_path}",
                hint="Provide a path to a file, not a directory",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.FILE_NOT_FOUND,
                    context={"file_path": file_path}
                )
            )
        
        if not os.access(file_path, os.R_OK):
            return ValidationResult(
                valid=False,
                reason=f"File is not readable: {file_path}",
                hint="Check file permissions",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.ACCESS_DENIED,
                    context={"file_path": file_path}
                )
            )
        
        return ValidationResult(valid=True)
    
    @staticmethod
    def validate_file_extension(file_path: str, expected_ext: str) -> ValidationResult:
        """
        Validate that a file has the expected extension.
        
        Args:
            file_path: Path to the file
            expected_ext: Expected file extension (e.g., ".shp", ".tif")
            
        Returns:
            ValidationResult with validation status
        """
        if not expected_ext:
            return ValidationResult(valid=True)  # No extension specified, skip validation
        
        file_ext = os.path.splitext(file_path)[1].lower()
        expected_ext = expected_ext.lower()
        
        if expected_ext and not expected_ext.startswith("."):
            expected_ext = f".{expected_ext}"
        
        if file_ext != expected_ext:
            return ValidationResult(
                valid=False,
                reason=f"File extension '{file_ext}' does not match expected '{expected_ext}'",
                hint=f"Ensure the file has the correct extension: {expected_ext}",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.INVALID_FILE_FORMAT,
                    context={
                        "file_path": file_path,
                        "actual_extension": file_ext,
                        "expected_extension": expected_ext,
                    }
                )
            )
        
        return ValidationResult(valid=True)
    
    @staticmethod
    def validate_driver(driver: str, driver_type: str = "auto") -> ValidationResult:
        """
        Validate that a GDAL driver is supported.
        
        Args:
            driver: GDAL driver name
            driver_type: Type of driver ("vector", "raster", or "auto")
            
        Returns:
            ValidationResult with validation status
        """
        if not driver:
            return ValidationResult(
                valid=False,
                reason="Driver is not specified",
                hint="Specify a valid GDAL driver",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.INVALID_DRIVER,
                    context={"driver": driver}
                )
            )
        
        all_drivers = {**VECTOR_DRIVERS, **RASTER_DRIVERS}
        
        if driver_type == "vector":
            supported = driver in VECTOR_DRIVERS
        elif driver_type == "raster":
            supported = driver in RASTER_DRIVERS
        else:
            supported = driver in all_drivers
        
        if not supported:
            return ValidationResult(
                valid=False,
                reason=f"Driver '{driver}' is not supported",
                hint=f"Supported drivers: {list(all_drivers.keys())}",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.INVALID_DRIVER,
                    context={"driver": driver, "driver_type": driver_type}
                )
            )
        
        return ValidationResult(valid=True)
    
    @staticmethod
    def validate_conversion_pair(
        input_driver: str,
        output_driver: str
    ) -> ConversionPairValidation:
        """
        Validate that a conversion pair is supported.
        
        Args:
            input_driver: Input GDAL driver
            output_driver: Output GDAL driver
            
        Returns:
            ConversionPairValidation with validation status
        """
        if not input_driver or not output_driver:
            return ConversionPairValidation(
                valid=False,
                reason="Input and output drivers must be specified"
            )
        
        # Check if the conversion pair is supported
        pair = (input_driver, output_driver)
        is_supported = SUPPORTED_CONVERSIONS.get(pair, False)
        
        if is_supported:
            return ConversionPairValidation(
                valid=True,
                supported_conversions=list(SUPPORTED_CONVERSIONS.keys())
            )
        
        # Check if drivers are valid individually
        input_valid = ValidationService.validate_driver(input_driver)
        output_valid = ValidationService.validate_driver(output_driver)
        
        if not input_valid.valid:
            return ConversionPairValidation(
                valid=False,
                reason=f"Invalid input driver: {input_valid.reason}"
            )
        
        if not output_valid.valid:
            return ConversionPairValidation(
                valid=False,
                reason=f"Invalid output driver: {output_valid.reason}"
            )
        
        # Drivers are valid but conversion is not supported
        return ConversionPairValidation(
            valid=False,
            reason=f"Conversion from '{input_driver}' to '{output_driver}' is not supported",
            supported_conversions=list(SUPPORTED_CONVERSIONS.keys())
        )
    
    @staticmethod
    def validate_input_path(
        input_path: str,
        input_driver_ext: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate an input file path for GDAL operations.
        
        Args:
            input_path: Path to the input file
            input_driver_ext: Expected file extension for the driver
            
        Returns:
            ValidationResult with validation status
        """
        # Check if it's a directory
        if os.path.isdir(input_path):
            # For directories, check if it contains matching files
            if input_driver_ext:
                matched_files = []
                for root, dirs, files in os.walk(input_path):
                    for file in files:
                        if file.lower().endswith(input_driver_ext.lower()):
                            matched_files.append(os.path.join(root, file))
                
                if matched_files:
                    return ValidationResult(
                        valid=True,
                        context={
                            "kind": "directory",
                            "matched_files": matched_files,
                            "file_count": len(matched_files),
                        }
                    )
                else:
                    return ValidationResult(
                        valid=False,
                        reason=f"No files with extension '{input_driver_ext}' found in directory",
                        hint="Ensure the directory contains files with the expected extension",
                        context={"kind": "directory", "matched_files": []}
                    )
            else:
                return ValidationResult(
                    valid=False,
                    reason="Directory provided but no file extension specified",
                    hint="Specify the expected file extension to search in the directory",
                    context={"kind": "directory"}
                )
        
        # Single file validation
        file_exists = ValidationService.validate_file_exists(input_path)
        if not file_exists.valid:
            return file_exists
        
        # Validate extension if specified
        if input_driver_ext:
            ext_validation = ValidationService.validate_file_extension(
                input_path, input_driver_ext
            )
            if not ext_validation.valid:
                return ValidationResult(
                    valid=False,
                    reason=ext_validation.reason,
                    hint=ext_validation.hint,
                    context={"kind": "file", "matched_files": [input_path]}
                )
        
        return ValidationResult(
            valid=True,
            context={"kind": "file", "matched_files": [input_path]}
        )
    
    @staticmethod
    def validate_output_directory(output_dir: str) -> ValidationResult:
        """
        Validate that an output directory exists and is writable.
        
        Args:
            output_dir: Path to the output directory
            
        Returns:
            ValidationResult with validation status
        """
        if not output_dir:
            return ValidationResult(
                valid=False,
                reason="Output directory is not specified",
                hint="Provide a valid output directory path"
            )
        
        # Create directory if it doesn't exist
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                return ValidationResult(
                    valid=False,
                    reason=f"Failed to create output directory: {output_dir}",
                    hint="Check permissions and path validity",
                    error_detail=ErrorCatalog.create_file_io_error(
                        str(e),
                        context={"output_dir": output_dir}
                    )
                )
        
        # Check if it's writable
        if not os.access(output_dir, os.W_OK):
            return ValidationResult(
                valid=False,
                reason=f"Output directory is not writable: {output_dir}",
                hint="Check directory permissions",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.ACCESS_DENIED,
                    context={"output_dir": output_dir}
                )
            )
        
        # Check disk space (basic check)
        try:
            stat = os.statvfs(output_dir) if hasattr(os, 'statvfs') else None
            if stat and stat.f_bavail * stat.f_frsize < 1024 * 1024:  # Less than 1MB
                return ValidationResult(
                    valid=False,
                    reason="Insufficient disk space in output directory",
                    hint="Free up disk space or choose a different location",
                    error_detail=ErrorCatalog.get_error(
                        ErrorCode.DISK_SPACE_EXCEEDED,
                        context={"output_dir": output_dir}
                    )
                )
        except Exception:
            pass  # Skip disk space check if not available
        
        return ValidationResult(valid=True)
    
    @staticmethod
    def validate_conversion_parameters(params: Dict[str, Any]) -> ValidationResult:
        """
        Validate conversion parameters.
        
        Args:
            params: Dictionary of conversion parameters
            
        Returns:
            ValidationResult with validation status
        """
        required_fields = ["task_id", "input_path", "input_driver", "conversion_driver"]
        
        for field in required_fields:
            if field not in params or not params[field]:
                return ValidationResult(
                    valid=False,
                    reason=f"Required parameter '{field}' is missing or empty",
                    hint=f"Provide all required parameters: {required_fields}",
                    error_detail=ErrorCatalog.create_validation_error(
                        f"Missing required parameter: {field}",
                        context={"missing_field": field, "provided_params": list(params.keys())}
                    )
                )
        
        # Validate task_id format (UUID-like)
        task_id = params.get("task_id", "")
        if not re.match(r'^[a-f0-9\-]{36}$', task_id):
            return ValidationResult(
                valid=False,
                reason="task_id must be a valid UUID",
                hint="Provide a valid UUID string",
                error_detail=ErrorCatalog.create_validation_error(
                    "Invalid task_id format",
                    context={"task_id": task_id}
                )
            )
        
        return ValidationResult(valid=True)
    
    @staticmethod
    def validate_file_with_gdal(file_path: str) -> ValidationResult:
        """
        Validate a file using GDAL to check if it's a valid geospatial file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            ValidationResult with validation status
        """
        # First check basic file existence
        basic_validation = ValidationService.validate_file_exists(file_path)
        if not basic_validation.valid:
            return basic_validation
        
        try:
            metadata = MetadataService.extract_metadata(file_path)
            
            if not metadata.is_valid:
                return ValidationResult(
                    valid=False,
                    reason=metadata.error_message or "File is not a valid geospatial file",
                    hint="Ensure the file is a valid GDAL-supported format",
                    error_detail=ErrorCatalog.get_error(
                        ErrorCode.FILE_CORRUPTED,
                        context={"file_path": file_path}
                    )
                )
            
            return ValidationResult(
                valid=True,
                context={
                    "driver": metadata.driver,
                    "file_type": metadata.file_type,
                    "is_valid": metadata.is_valid,
                }
            )
        except Exception as e:
            return ValidationResult(
                valid=False,
                reason=f"GDAL validation failed: {str(e)}",
                hint="Ensure the file is a valid geospatial format",
                error_detail=ErrorCatalog.get_error(
                    ErrorCode.FILE_CORRUPTED,
                    technical_message=str(e),
                    context={"file_path": file_path}
                )
            )
    
    @staticmethod
    def get_supported_conversions() -> List[Tuple[str, str]]:
        """
        Get list of all supported conversion pairs.
        
        Returns:
            List of (input_driver, output_driver) tuples
        """
        return list(SUPPORTED_CONVERSIONS.keys())
    
    @staticmethod
    def get_supported_drivers(driver_type: str = "all") -> List[str]:
        """
        Get list of supported GDAL drivers.
        
        Args:
            driver_type: Type of drivers to return ("vector", "raster", or "all")
            
        Returns:
            List of driver names
        """
        if driver_type == "vector":
            return list(VECTOR_DRIVERS.keys())
        elif driver_type == "raster":
            return list(RASTER_DRIVERS.keys())
        else:
            return list({**VECTOR_DRIVERS, **RASTER_DRIVERS}.keys())
