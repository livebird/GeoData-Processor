"""
Framework-agnostic service layer for GDAL processing operations.

This package contains business logic that can be called by both Django REST Framework
views and Celery tasks, with no framework coupling. This is the most important boundary
in the codebase as per SRS §3.2 principle 3.

Service modules:
- gdal_runner: Main orchestration for GDAL operations
- metadata: GDAL metadata extraction
- validation: File and conversion validation
- transformation: Format conversion logic
- preview: Preview generation (summary, features, attributes)
- dispatch: Layer dispatch operations
- remote_ingest: Remote file ingestion
- error_catalog: Error handling and cataloging
"""

from .gdal_runner import GDALRunner
from .metadata import MetadataService
from .validation import ValidationService
from .transformation import TransformationService
from .preview import PreviewService
from .dispatch import DispatchService
from .remote_ingest import RemoteIngestService
from .error_catalog import ErrorCatalog

__all__ = [
    'GDALRunner',
    'MetadataService',
    'ValidationService',
    'TransformationService',
    'PreviewService',
    'DispatchService',
    'RemoteIngestService',
    'ErrorCatalog',
]
