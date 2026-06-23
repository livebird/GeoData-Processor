"""
Preview generation service for GDAL operations.

This module provides framework-agnostic preview generation for geospatial files,
including summary statistics, feature previews, and attribute previews. It can be
called by both Django REST Framework views and Celery tasks.
"""

import os
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

try:
    import geopandas as gpd
    import rasterio
    import numpy as np
    import pandas as pd
except ImportError as e:
    print(f"Warning: Missing library: {e}")
    gpd = None
    rasterio = None
    np = None
    pd = None

from .metadata import MetadataService
from .error_catalog import ErrorCatalog, ErrorCode


@dataclass
class PreviewSummary:
    """Summary preview of a geospatial file."""
    file_type: str  # 'vector' or 'raster'
    feature_count: Optional[int] = None
    geometry_count: Optional[int] = None
    layer_count: Optional[int] = None
    extent: Optional[Dict[str, float]] = None
    crs: Optional[str] = None
    field_names: Optional[List[str]] = None
    raster_dimensions: Optional[Dict[str, int]] = None
    data_type: Optional[str] = None
    band_count: Optional[int] = None
    file_size: Optional[int] = None


@dataclass
class FeaturePreview:
    """Preview of vector features (GeoJSON format)."""
    features: List[Dict[str, Any]]
    total_count: int
    returned_count: int
    page: int
    page_size: int
    has_more: bool


@dataclass
class AttributePreview:
    """Preview of attribute data (tabular format)."""
    columns: List[str]
    data: List[Dict[str, Any]]
    total_count: int
    returned_count: int
    page: int
    page_size: int
    has_more: bool
    column_types: Optional[Dict[str, str]] = None


class PreviewService:
    """
    Framework-agnostic service for generating previews of geospatial files.
    
    This service provides three types of previews:
    - Summary: High-level information about the file
    - Features: Paginated GeoJSON feature preview
    - Attributes: Paginated attribute table preview
    """
    
    @staticmethod
    def _check_dependencies() -> None:
        """Check if required dependencies are available."""
        if gpd is None:
            raise ImportError(
                "geopandas is required for vector previews. "
                "Install it using: pip install geopandas"
            )
        if rasterio is None:
            raise ImportError(
                "rasterio is required for raster previews. "
                "Install it using: pip install rasterio"
            )
        if pd is None:
            raise ImportError(
                "pandas is required for attribute previews. "
                "Install it using: pip install pandas"
            )
    
    @staticmethod
    def generate_summary(file_path: str) -> PreviewSummary:
        """
        Generate a summary preview of a geospatial file.
        
        Args:
            file_path: Path to the geospatial file
            
        Returns:
            PreviewSummary with file information
        """
        try:
            # Get metadata
            metadata = MetadataService.extract_metadata(file_path)
            
            if not metadata.is_valid:
                return PreviewSummary(
                    file_type="unknown",
                    error_message=metadata.error_message
                )
            
            # Get file size
            file_size = metadata.file_size
            
            if metadata.file_type == "vector":
                # Vector summary
                layer_metadata = metadata.layer_metadata or []
                total_features = sum(layer.feature_count for layer in layer_metadata)
                
                # Get field names from first layer
                field_names = []
                if layer_metadata:
                    field_names = [field["name"] for field in layer_metadata[0].fields]
                
                # Get extent from first layer
                extent = None
                if layer_metadata and layer_metadata[0].extent:
                    extent = layer_metadata[0].extent
                
                # Get CRS from first layer
                crs = None
                if layer_metadata:
                    crs = layer_metadata[0].srs
                
                return PreviewSummary(
                    file_type="vector",
                    feature_count=total_features,
                    geometry_count=total_features,
                    layer_count=len(layer_metadata),
                    extent=extent,
                    crs=crs,
                    field_names=field_names,
                    file_size=file_size,
                )
            
            elif metadata.file_type == "raster":
                # Raster summary
                raster_meta = metadata.raster_metadata
                
                return PreviewSummary(
                    file_type="raster",
                    extent=raster_meta.extent if raster_meta else None,
                    crs=raster_meta.srs if raster_meta else None,
                    raster_dimensions={
                        "width": raster_meta.width if raster_meta else 0,
                        "height": raster_meta.height if raster_meta else 0,
                    },
                    data_type=raster_meta.data_type if raster_meta else None,
                    band_count=raster_meta.band_count if raster_meta else 0,
                    file_size=file_size,
                )
            
            else:
                return PreviewSummary(
                    file_type="unknown",
                    error_message="Unknown file type"
                )
                
        except Exception as e:
            return PreviewSummary(
                file_type="unknown",
                error_message=f"Failed to generate summary: {str(e)}"
            )
    
    @staticmethod
    def generate_feature_preview(
        file_path: str,
        page: int = 1,
        page_size: int = 100,
        layer_name: Optional[str] = None
    ) -> FeaturePreview:
        """
        Generate a paginated feature preview (GeoJSON).
        
        Args:
            file_path: Path to the vector file
            page: Page number (1-indexed)
            page_size: Number of features per page
            layer_name: Specific layer to preview (for multi-layer files)
            
        Returns:
            FeaturePreview with paginated features
        """
        PreviewService._check_dependencies()
        
        try:
            # Read the file
            gdf = gpd.read_file(file_path, layer=layer_name)
            
            total_count = len(gdf)
            offset = (page - 1) * page_size
            limit = min(page_size, total_count - offset)
            
            # Paginate
            gdf_page = gdf.iloc[offset:offset + limit]
            
            # Convert to GeoJSON-like format
            features = []
            for idx, row in gdf_page.iterrows():
                feature = {
                    "type": "Feature",
                    "geometry": row.geometry.__geo_interface__ if row.geometry else None,
                    "properties": {
                        k: v for k, v in row.items() if k != 'geometry'
                    }
                }
                features.append(feature)
            
            has_more = offset + limit < total_count
            
            return FeaturePreview(
                features=features,
                total_count=total_count,
                returned_count=len(features),
                page=page,
                page_size=page_size,
                has_more=has_more,
            )
            
        except Exception as e:
            return FeaturePreview(
                features=[],
                total_count=0,
                returned_count=0,
                page=page,
                page_size=page_size,
                has_more=False,
            )
    
    @staticmethod
    def generate_attribute_preview(
        file_path: str,
        page: int = 1,
        page_size: int = 100,
        layer_name: Optional[str] = None
    ) -> AttributePreview:
        """
        Generate a paginated attribute preview (tabular data).
        
        Args:
            file_path: Path to the vector file
            page: Page number (1-indexed)
            page_size: Number of rows per page
            layer_name: Specific layer to preview (for multi-layer files)
            
        Returns:
            AttributePreview with paginated attributes
        """
        PreviewService._check_dependencies()
        
        try:
            # Read the file
            gdf = gpd.read_file(file_path, layer=layer_name)
            
            # Drop geometry column for attribute preview
            df = gdf.drop(columns=['geometry'], errors=True)
            
            total_count = len(df)
            offset = (page - 1) * page_size
            limit = min(page_size, total_count - offset)
            
            # Paginate
            df_page = df.iloc[offset:offset + limit]
            
            # Get column names and types
            columns = list(df.columns)
            column_types = {col: str(df[col].dtype) for col in columns}
            
            # Convert to list of dictionaries
            data = df_page.to_dict('records')
            
            # Convert NaN to None for JSON serialization
            for row in data:
                for key, value in row.items():
                    if pd.isna(value):
                        row[key] = None
            
            has_more = offset + limit < total_count
            
            return AttributePreview(
                columns=columns,
                data=data,
                total_count=total_count,
                returned_count=len(data),
                page=page,
                page_size=page_size,
                has_more=has_more,
                column_types=column_types,
            )
            
        except Exception as e:
            return AttributePreview(
                columns=[],
                data=[],
                total_count=0,
                returned_count=0,
                page=page,
                page_size=page_size,
                has_more=False,
                column_types={},
            )
    
    @staticmethod
    def generate_raster_preview(
        file_path: str,
        max_size: int = 1024
    ) -> Dict[str, Any]:
        """
        Generate a raster preview (statistics and sample data).
        
        Args:
            file_path: Path to the raster file
            max_size: Maximum dimension for preview (for downsampling)
            
        Returns:
            Dictionary with raster preview information
        """
        PreviewService._check_dependencies()
        
        try:
            with rasterio.open(file_path) as src:
                # Get basic info
                width = src.width
                height = src.height
                band_count = src.count
                
                # Calculate statistics for each band
                band_stats = []
                for i in range(1, band_count + 1):
                    band = src.read(i)
                    stats = {
                        "band": i,
                        "min": float(band.min()),
                        "max": float(band.max()),
                        "mean": float(band.mean()),
                        "std": float(band.std()),
                        "nodata": src.nodatavals[i - 1],
                        "dtype": str(band.dtype),
                    }
                    band_stats.append(stats)
                
                # Get extent
                extent = {
                    "left": src.bounds.left,
                    "bottom": src.bounds.bottom,
                    "right": src.bounds.right,
                    "top": src.bounds.top,
                }
                
                # Get CRS
                crs = str(src.crs) if src.crs else None
                
                return {
                    "width": width,
                    "height": height,
                    "band_count": band_count,
                    "extent": extent,
                    "crs": crs,
                    "band_statistics": band_stats,
                    "transform": list(src.transform),
                }
                
        except Exception as e:
            return {
                "error": f"Failed to generate raster preview: {str(e)}"
            }
    
    @staticmethod
    def summary_to_dict(summary: PreviewSummary) -> Dict[str, Any]:
        """
        Convert PreviewSummary to dictionary for API responses.
        
        Args:
            summary: PreviewSummary object
            
        Returns:
            Dictionary representation
        """
        result = {
            "file_type": summary.file_type,
        }
        
        if summary.feature_count is not None:
            result["feature_count"] = summary.feature_count
        
        if summary.geometry_count is not None:
            result["geometry_count"] = summary.geometry_count
        
        if summary.layer_count is not None:
            result["layer_count"] = summary.layer_count
        
        if summary.extent is not None:
            result["extent"] = summary.extent
        
        if summary.crs is not None:
            result["crs"] = summary.crs
        
        if summary.field_names is not None:
            result["field_names"] = summary.field_names
        
        if summary.raster_dimensions is not None:
            result["raster_dimensions"] = summary.raster_dimensions
        
        if summary.data_type is not None:
            result["data_type"] = summary.data_type
        
        if summary.band_count is not None:
            result["band_count"] = summary.band_count
        
        if summary.file_size is not None:
            result["file_size"] = summary.file_size
        
        if hasattr(summary, 'error_message') and summary.error_message:
            result["error_message"] = summary.error_message
        
        return result
    
    @staticmethod
    def feature_preview_to_dict(preview: FeaturePreview) -> Dict[str, Any]:
        """
        Convert FeaturePreview to dictionary for API responses.
        
        Args:
            preview: FeaturePreview object
            
        Returns:
            Dictionary representation
        """
        return {
            "type": "FeatureCollection",
            "features": preview.features,
            "pagination": {
                "total_count": preview.total_count,
                "returned_count": preview.returned_count,
                "page": preview.page,
                "page_size": preview.page_size,
                "has_more": preview.has_more,
            }
        }
    
    @staticmethod
    def attribute_preview_to_dict(preview: AttributePreview) -> Dict[str, Any]:
        """
        Convert AttributePreview to dictionary for API responses.
        
        Args:
            preview: AttributePreview object
            
        Returns:
            Dictionary representation
        """
        return {
            "columns": preview.columns,
            "data": preview.data,
            "column_types": preview.column_types,
            "pagination": {
                "total_count": preview.total_count,
                "returned_count": preview.returned_count,
                "page": preview.page,
                "page_size": preview.page_size,
                "has_more": preview.has_more,
            }
        }
