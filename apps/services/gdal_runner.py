"""
GDAL Runner - Main orchestration service for GDAL operations.

This module provides the main orchestration layer that coordinates all other
services (metadata, validation, transformation, preview, dispatch, remote_ingest)
to provide a high-level, framework-agnostic API for GDAL operations. It can be
called by both Django REST Framework views and Celery tasks.

This is the primary entry point for GDAL operations in the service layer.
"""

import os
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import threading
import json

from .metadata import MetadataService, FileMetadata
from .validation import ValidationService, ValidationResult
from .transformation import TransformationService, TransformationResult, TransformationOptions
from .preview import PreviewService, PreviewSummary, FeaturePreview, AttributePreview
from .dispatch import DispatchService, DispatchResult, DestinationCredential
from .remote_ingest import RemoteIngestService, IngestResult, IngestOptions
from .error_catalog import ErrorCatalog, ErrorCode


@dataclass
class JobStatus:
    """Status of a GDAL processing job."""
    task_id: str
    status: str  # queued, processing, completed, error, cancelled
    progress: float  # 0.0 to 1.0
    message: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output_files: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ConversionJob:
    """Configuration for a conversion job."""
    task_id: str
    input_path: str
    input_driver: str
    input_driver_ext: str
    conversion_driver: str
    conversion_driver_ext: str
    output_dir: str
    callback_url: Optional[str] = None
    conversion_kwargs: Optional[Dict[str, Any]] = None
    transformation_options: Optional[TransformationOptions] = None


class GDALRunner:
    """
    Main orchestration service for GDAL operations.
    
    This service provides a high-level API that coordinates all other services
    to perform complex GDAL operations including:
    - File validation and metadata extraction
    - Format conversion (vector-to-vector, raster-to-raster, etc.)
    - Preview generation (summary, features, attributes)
    - Remote file ingestion
    - Layer dispatch to external destinations
    
    This is the primary entry point for GDAL operations and is designed to be
    called from both Django views and Celery tasks without framework coupling.
    """
    
    def __init__(self, output_base_dir: Optional[str] = None):
        """
        Initialize the GDAL Runner.
        
        Args:
            output_base_dir: Base directory for output files
        """
        if output_base_dir is None:
            output_base_dir = os.path.join(os.path.dirname(__file__), "outputs")
        
        self.output_base_dir = output_base_dir
        os.makedirs(output_base_dir, exist_ok=True)
    
    def validate_conversion_request(
        self,
        input_path: str,
        input_driver: str,
        output_driver: str,
        input_driver_ext: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate a conversion request.
        
        Args:
            input_path: Path to input file
            input_driver: Input GDAL driver
            output_driver: Output GDAL driver
            input_driver_ext: Expected file extension
            
        Returns:
            Dictionary with validation results
        """
        # Validate input path
        input_validation = ValidationService.validate_input_path(
            input_path, input_driver_ext
        )
        
        if not input_validation.valid:
            return {
                "valid": False,
                "reason": input_validation.reason,
                "hint": input_validation.hint,
                "validation": input_validation.context,
            }
        
        # Validate conversion pair
        pair_validation = ValidationService.validate_conversion_pair(
            input_driver, output_driver
        )
        
        if not pair_validation.valid:
            return {
                "valid": False,
                "reason": pair_validation.reason,
                "supported_conversions": pair_validation.supported_conversions,
            }
        
        return {
            "valid": True,
            "validation": input_validation.context,
            "supported_conversions": pair_validation.supported_conversions,
        }
    
    def run_conversion(
        self,
        job: ConversionJob,
        status_callback: Optional[callable] = None
    ) -> TransformationResult:
        """
        Run a conversion job.
        
        Args:
            job: ConversionJob configuration
            status_callback: Optional callback for status updates
            
        Returns:
            TransformationResult with operation status
        """
        # Update status
        if status_callback:
            status_callback(job.task_id, "processing", 0.0, "Starting conversion")
        
        # Create task directory
        task_dir = os.path.join(self.output_base_dir, job.task_id)
        os.makedirs(task_dir, exist_ok=True)
        
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        
        # Determine output file path
        file_name = os.path.splitext(os.path.basename(job.input_path))[0]
        output_ext = job.conversion_driver_ext or ".tif"
        output_path = os.path.join(output_dir, f"{file_name}{output_ext}")
        
        # Determine conversion type
        input_is_vector = job.input_driver in ValidationService.get_supported_drivers("vector")
        output_is_vector = job.conversion_driver in ValidationService.get_supported_drivers("vector")
        
        try:
            # Run appropriate conversion
            if input_is_vector and output_is_vector:
                result = TransformationService.vector_to_vector(
                    job.input_path,
                    output_path,
                    job.input_driver,
                    job.conversion_driver,
                    job.transformation_options
                )
            elif not input_is_vector and not output_is_vector:
                result = TransformationService.raster_to_raster(
                    job.input_path,
                    output_path,
                    job.input_driver,
                    job.conversion_driver,
                    job.transformation_options
                )
            elif input_is_vector and not output_is_vector:
                result = TransformationService.vector_to_raster(
                    job.input_path,
                    output_path,
                    job.input_driver,
                    job.conversion_driver,
                    job.transformation_options
                )
            else:
                result = TransformationService.raster_to_vector(
                    job.input_path,
                    output_path,
                    job.input_driver,
                    job.conversion_driver,
                    job.transformation_options
                )
            
            # Create ZIP archive if successful
            if result.success and result.output_files:
                zip_path = os.path.join(task_dir, "output.zip")
                TransformationService.create_output_zip(result.output_files, zip_path)
                result.output_files.append(zip_path)
            
            # Update status
            if status_callback:
                if result.success:
                    status_callback(job.task_id, "completed", 1.0, "Conversion completed")
                else:
                    status_callback(job.task_id, "error", 0.0, result.error_message)
            
            return result
            
        except Exception as e:
            error_result = TransformationResult(
                success=False,
                error_message=f"Conversion failed: {str(e)}",
                error_detail={"error_type": type(e).__name__, "error_details": str(e)}
            )
            
            if status_callback:
                status_callback(job.task_id, "error", 0.0, str(e))
            
            return error_result
    
    def run_conversion_async(
        self,
        job: ConversionJob,
        status_file: Optional[str] = None
    ) -> str:
        """
        Run a conversion job asynchronously in a background thread.
        
        Args:
            job: ConversionJob configuration
            status_file: Optional file to write status updates
            
        Returns:
            Task ID
        """
        def _run_with_callback():
            def status_callback(task_id, status, progress, message):
                status_data = {
                    "task_id": task_id,
                    "status": status,
                    "progress": progress,
                    "message": message,
                    "updated_at": datetime.now().isoformat(),
                }
                
                if status_file:
                    os.makedirs(os.path.dirname(status_file), exist_ok=True)
                    with open(status_file, 'w') as f:
                        json.dump(status_data, f)
                
                # Call callback URL if provided
                if job.callback_url:
                    try:
                        import requests
                        requests.post(job.callback_url, json=status_data, timeout=10)
                    except Exception:
                        pass
            
            result = self.run_conversion(job, status_callback)
            
            # Write final status
            if status_file:
                final_status = {
                    "task_id": job.task_id,
                    "status": "completed" if result.success else "error",
                    "progress": 1.0,
                    "message": result.error_message if not result.success else "Conversion completed",
                    "output_files": result.output_files,
                    "metadata": result.metadata,
                    "finished_at": datetime.now().isoformat(),
                }
                with open(status_file, 'w') as f:
                    json.dump(final_status, f)
        
        # Start thread
        thread = threading.Thread(target=_run_with_callback)
        thread.daemon = True
        thread.start()
        
        return job.task_id
    
    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Get metadata for a geospatial file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with file metadata
        """
        metadata = MetadataService.extract_metadata(file_path)
        return MetadataService.metadata_to_dict(metadata)
    
    def generate_preview_summary(self, file_path: str) -> Dict[str, Any]:
        """
        Generate a summary preview of a geospatial file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with summary preview
        """
        summary = PreviewService.generate_summary(file_path)
        return PreviewService.summary_to_dict(summary)
    
    def generate_feature_preview(
        self,
        file_path: str,
        page: int = 1,
        page_size: int = 100,
        layer_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a paginated feature preview.
        
        Args:
            file_path: Path to the vector file
            page: Page number
            page_size: Features per page
            layer_name: Specific layer to preview
            
        Returns:
            Dictionary with feature preview
        """
        preview = PreviewService.generate_feature_preview(
            file_path, page, page_size, layer_name
        )
        return PreviewService.feature_preview_to_dict(preview)
    
    def generate_attribute_preview(
        self,
        file_path: str,
        page: int = 1,
        page_size: int = 100,
        layer_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a paginated attribute preview.
        
        Args:
            file_path: Path to the vector file
            page: Page number
            page_size: Rows per page
            layer_name: Specific layer to preview
            
        Returns:
            Dictionary with attribute preview
        """
        preview = PreviewService.generate_attribute_preview(
            file_path, page, page_size, layer_name
        )
        return PreviewService.attribute_preview_to_dict(preview)
    
    def ingest_remote_file(
        self,
        url: str,
        output_dir: Optional[str] = None,
        **options
    ) -> IngestResult:
        """
        Ingest a file from a remote URL.
        
        Args:
            url: Remote URL
            output_dir: Directory to save the file
            **options: Additional ingest options
            
        Returns:
            IngestResult with operation status
        """
        ingest_options = IngestOptions(
            output_dir=output_dir or self.output_base_dir,
            **options
        )
        
        return RemoteIngestService.ingest_from_url(url, ingest_options)
    
    def dispatch_layer(
        self,
        file_path: str,
        credential: DestinationCredential,
        layer_name: Optional[str] = None,
        **kwargs
    ) -> DispatchResult:
        """
        Dispatch a layer to an external destination.
        
        Args:
            file_path: Path to the file
            credential: Destination credential
            layer_name: Name of the layer to dispatch
            **kwargs: Additional dispatch parameters
            
        Returns:
            DispatchResult with operation status
        """
        return DispatchService.dispatch(
            file_path, credential, layer_name, **kwargs
        )
    
    def get_supported_conversions(self) -> List[tuple]:
        """
        Get list of supported conversion pairs.
        
        Returns:
            List of (input_driver, output_driver) tuples
        """
        return ValidationService.get_supported_conversions()
    
    def get_supported_drivers(self, driver_type: str = "all") -> List[str]:
        """
        Get list of supported GDAL drivers.
        
        Args:
            driver_type: Type of drivers ("vector", "raster", or "all")
            
        Returns:
            List of driver names
        """
        return ValidationService.get_supported_drivers(driver_type)
    
    def create_conversion_job(
        self,
        input_path: str,
        input_driver: str,
        output_driver: str,
        input_driver_ext: Optional[str] = None,
        output_driver_ext: Optional[str] = None,
        callback_url: Optional[str] = None,
        conversion_kwargs: Optional[Dict[str, Any]] = None,
        transformation_options: Optional[TransformationOptions] = None
    ) -> ConversionJob:
        """
        Create a conversion job configuration.
        
        Args:
            input_path: Path to input file
            input_driver: Input GDAL driver
            output_driver: Output GDAL driver
            input_driver_ext: Input file extension
            output_driver_ext: Output file extension
            callback_url: Optional callback URL for status updates
            conversion_kwargs: Additional conversion parameters
            transformation_options: Transformation options
            
        Returns:
            ConversionJob configuration
        """
        task_id = str(uuid.uuid4())
        
        return ConversionJob(
            task_id=task_id,
            input_path=input_path,
            input_driver=input_driver,
            input_driver_ext=input_driver_ext or "",
            conversion_driver=output_driver,
            conversion_driver_ext=output_driver_ext or ".tif",
            output_dir=self.output_base_dir,
            callback_url=callback_url,
            conversion_kwargs=conversion_kwargs or {},
            transformation_options=transformation_options,
        )
    
    def get_job_status(self, task_id: str, status_file: Optional[str] = None) -> Optional[JobStatus]:
        """
        Get the status of a job.
        
        Args:
            task_id: Task ID
            status_file: Optional status file path
            
        Returns:
            JobStatus if found, None otherwise
        """
        if status_file and os.path.exists(status_file):
            try:
                with open(status_file, 'r') as f:
                    status_data = json.load(f)
                
                return JobStatus(
                    task_id=status_data.get("task_id", task_id),
                    status=status_data.get("status", "unknown"),
                    progress=status_data.get("progress", 0.0),
                    message=status_data.get("message"),
                    error_message=status_data.get("error_message"),
                    started_at=status_data.get("started_at"),
                    finished_at=status_data.get("finished_at"),
                    output_files=status_data.get("output_files"),
                    metadata=status_data.get("metadata"),
                )
            except Exception:
                pass
        
        # Check if output exists
        task_dir = os.path.join(self.output_base_dir, task_id)
        if os.path.exists(task_dir):
            output_zip = os.path.join(task_dir, "output.zip")
            if os.path.exists(output_zip):
                return JobStatus(
                    task_id=task_id,
                    status="completed",
                    progress=1.0,
                    message="Conversion completed",
                    output_files=[output_zip],
                )
        
        return None
    
    def get_job_output(self, task_id: str) -> Optional[str]:
        """
        Get the output file path for a job.
        
        Args:
            task_id: Task ID
            
        Returns:
            Path to output ZIP file if found, None otherwise
        """
        task_dir = os.path.join(self.output_base_dir, task_id)
        output_zip = os.path.join(task_dir, "output.zip")
        
        if os.path.exists(output_zip):
            return output_zip
        
        return None
