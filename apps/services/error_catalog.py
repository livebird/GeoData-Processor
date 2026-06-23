"""
Error catalog and handling service for GDAL operations.

This module provides a centralized error handling system with categorized error types,
user-friendly messages, and error codes for the GDAL processing service.
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass


class ErrorCategory(Enum):
    """Categories of errors that can occur during GDAL operations."""
    VALIDATION = "validation"
    CONVERSION = "conversion"
    METADATA = "metadata"
    FILE_IO = "file_io"
    NETWORK = "network"
    DATABASE = "database"
    PERMISSION = "permission"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class ErrorCode(Enum):
    """Specific error codes with machine-readable identifiers."""
    
    # Validation errors
    INVALID_FILE_FORMAT = "VAL001"
    UNSUPPORTED_CONVERSION = "VAL002"
    FILE_NOT_FOUND = "VAL003"
    FILE_CORRUPTED = "VAL004"
    INVALID_DRIVER = "VAL005"
    
    # Conversion errors
    CONVERSION_FAILED = "CONV001"
    GDAL_ERROR = "CONV002"
    MEMORY_LIMIT_EXCEEDED = "CONV003"
    TIMEOUT = "CONV004"
    
    # Metadata errors
    METADATA_EXTRACTION_FAILED = "META001"
    UNSUPPORTED_METADATA_FORMAT = "META002"
    
    # File I/O errors
    READ_ERROR = "IO001"
    WRITE_ERROR = "IO002"
    DISK_SPACE_EXCEEDED = "IO003"
    
    # Network errors
    DOWNLOAD_FAILED = "NET001"
    CONNECTION_TIMEOUT = "NET002"
    INVALID_URL = "NET003"
    
    # Database errors
    DB_CONNECTION_ERROR = "DB001"
    DB_QUERY_ERROR = "DB002"
    
    # Permission errors
    ACCESS_DENIED = "PERM001"
    INSUFFICIENT_PRIVILEGES = "PERM002"
    
    # Resource errors
    RESOURCE_NOT_FOUND = "RES001"
    RESOURCE_LOCKED = "RES002"


@dataclass
class ErrorDetail:
    """Detailed error information."""
    code: ErrorCode
    category: ErrorCategory
    message: str
    technical_message: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    severity: str = "error"  # error, warning, info
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error detail to dictionary for API responses."""
        return {
            "code": self.code.value,
            "category": self.category.value,
            "message": self.message,
            "technical_message": self.technical_message,
            "context": self.context or {},
            "severity": self.severity,
        }


class ErrorCatalog:
    """
    Centralized error catalog with predefined error messages and handling logic.
    
    This service provides a consistent way to handle and report errors across
    the application, ensuring that error messages are user-friendly and
    machine-readable.
    
    Implements FR-VAL-004 and FR-VAL-005 for severity-based dispatch blocking.
    """
    
    # Severity levels for dispatch blocking (FR-VAL-004, FR-VAL-005)
    SEVERITY_BLOCKING = {"error", "critical"}  # These block dispatch
    SEVERITY_NON_BLOCKING = {"info", "warning"}  # These allow processing to proceed
    
    # Predefined error messages
    ERROR_MESSAGES: Dict[ErrorCode, str] = {
        # Validation errors
        ErrorCode.INVALID_FILE_FORMAT: "The file format is not supported or invalid.",
        ErrorCode.UNSUPPORTED_CONVERSION: "The requested conversion is not supported.",
        ErrorCode.FILE_NOT_FOUND: "The specified file could not be found.",
        ErrorCode.FILE_CORRUPTED: "The file appears to be corrupted or unreadable.",
        ErrorCode.INVALID_DRIVER: "The specified GDAL driver is invalid or not available.",
        
        # Conversion errors
        ErrorCode.CONVERSION_FAILED: "The conversion operation failed.",
        ErrorCode.GDAL_ERROR: "A GDAL library error occurred during processing.",
        ErrorCode.MEMORY_LIMIT_EXCEEDED: "The operation exceeded available memory limits.",
        ErrorCode.TIMEOUT: "The operation timed out.",
        
        # Metadata errors
        ErrorCode.METADATA_EXTRACTION_FAILED: "Failed to extract metadata from the file.",
        ErrorCode.UNSUPPORTED_METADATA_FORMAT: "The metadata format is not supported.",
        
        # File I/O errors
        ErrorCode.READ_ERROR: "Failed to read the file.",
        ErrorCode.WRITE_ERROR: "Failed to write the output file.",
        ErrorCode.DISK_SPACE_EXCEEDED: "Insufficient disk space for the operation.",
        
        # Network errors
        ErrorCode.DOWNLOAD_FAILED: "Failed to download the remote file.",
        ErrorCode.CONNECTION_TIMEOUT: "Network connection timed out.",
        ErrorCode.INVALID_URL: "The provided URL is invalid.",
        
        # Database errors
        ErrorCode.DB_CONNECTION_ERROR: "Failed to connect to the database.",
        ErrorCode.DB_QUERY_ERROR: "A database query error occurred.",
        
        # Permission errors
        ErrorCode.ACCESS_DENIED: "Access to the resource was denied.",
        ErrorCode.INSUFFICIENT_PRIVILEGES: "Insufficient privileges to perform the operation.",
        
        # Resource errors
        ErrorCode.RESOURCE_NOT_FOUND: "The requested resource was not found.",
        ErrorCode.RESOURCE_LOCKED: "The resource is currently locked and unavailable.",
    }
    
    # Error category mappings
    ERROR_CATEGORIES: Dict[ErrorCode, ErrorCategory] = {
        ErrorCode.INVALID_FILE_FORMAT: ErrorCategory.VALIDATION,
        ErrorCode.UNSUPPORTED_CONVERSION: ErrorCategory.VALIDATION,
        ErrorCode.FILE_NOT_FOUND: ErrorCategory.VALIDATION,
        ErrorCode.FILE_CORRUPTED: ErrorCategory.VALIDATION,
        ErrorCode.INVALID_DRIVER: ErrorCategory.VALIDATION,
        
        ErrorCode.CONVERSION_FAILED: ErrorCategory.CONVERSION,
        ErrorCode.GDAL_ERROR: ErrorCategory.CONVERSION,
        ErrorCode.MEMORY_LIMIT_EXCEEDED: ErrorCategory.CONVERSION,
        ErrorCode.TIMEOUT: ErrorCategory.CONVERSION,
        
        ErrorCode.METADATA_EXTRACTION_FAILED: ErrorCategory.METADATA,
        ErrorCode.UNSUPPORTED_METADATA_FORMAT: ErrorCategory.METADATA,
        
        ErrorCode.READ_ERROR: ErrorCategory.FILE_IO,
        ErrorCode.WRITE_ERROR: ErrorCategory.FILE_IO,
        ErrorCode.DISK_SPACE_EXCEEDED: ErrorCategory.FILE_IO,
        
        ErrorCode.DOWNLOAD_FAILED: ErrorCategory.NETWORK,
        ErrorCode.CONNECTION_TIMEOUT: ErrorCategory.NETWORK,
        ErrorCode.INVALID_URL: ErrorCategory.NETWORK,
        
        ErrorCode.DB_CONNECTION_ERROR: ErrorCategory.DATABASE,
        ErrorCode.DB_QUERY_ERROR: ErrorCategory.DATABASE,
        
        ErrorCode.ACCESS_DENIED: ErrorCategory.PERMISSION,
        ErrorCode.INSUFFICIENT_PRIVILEGES: ErrorCategory.PERMISSION,
        
        ErrorCode.RESOURCE_NOT_FOUND: ErrorCategory.RESOURCE,
        ErrorCode.RESOURCE_LOCKED: ErrorCategory.RESOURCE,
    }
    
    @classmethod
    def get_error(
        cls,
        code: ErrorCode,
        technical_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        severity: str = "error"
    ) -> ErrorDetail:
        """
        Get an error detail for a given error code.
        
        Args:
            code: The error code
            technical_message: Technical details for debugging
            context: Additional context about the error
            severity: Error severity (error, warning, info)
            
        Returns:
            ErrorDetail object with complete error information
        """
        message = cls.ERROR_MESSAGES.get(code, "An unknown error occurred.")
        category = cls.ERROR_CATEGORIES.get(code, ErrorCategory.UNKNOWN)
        
        return ErrorDetail(
            code=code,
            category=category,
            message=message,
            technical_message=technical_message,
            context=context,
            severity=severity
        )
    
    @classmethod
    def create_validation_error(
        cls,
        message: str,
        technical_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorDetail:
        """Create a custom validation error."""
        return ErrorDetail(
            code=ErrorCode.INVALID_FILE_FORMAT,
            category=ErrorCategory.VALIDATION,
            message=message,
            technical_message=technical_message,
            context=context
        )
    
    @classmethod
    def create_conversion_error(
        cls,
        message: str,
        technical_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorDetail:
        """Create a custom conversion error."""
        return ErrorDetail(
            code=ErrorCode.CONVERSION_FAILED,
            category=ErrorCategory.CONVERSION,
            message=message,
            technical_message=technical_message,
            context=context
        )
    
    @classmethod
    def create_file_io_error(
        cls,
        message: str,
        technical_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorDetail:
        """Create a custom file I/O error."""
        return ErrorDetail(
            code=ErrorCode.READ_ERROR,
            category=ErrorCategory.FILE_IO,
            message=message,
            technical_message=technical_message,
            context=context
        )
    
    @classmethod
    def create_network_error(
        cls,
        message: str,
        technical_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorDetail:
        """Create a custom network error."""
        return ErrorDetail(
            code=ErrorCode.DOWNLOAD_FAILED,
            category=ErrorCategory.NETWORK,
            message=message,
            technical_message=technical_message,
            context=context
        )
    
    @classmethod
    def should_block_dispatch(cls, errors: List[ErrorDetail]) -> bool:
        """
        Determine if dispatch should be blocked based on error severities.
        
        Implements FR-VAL-004: Blocks dispatch if error or critical severity issues exist.
        Implements FR-VAL-005: Allows processing past info and warning.
        
        Args:
            errors: List of ErrorDetail objects from validation
            
        Returns:
            True if dispatch should be blocked, False otherwise
        """
        for error in errors:
            if error.severity in cls.SEVERITY_BLOCKING:
                return True
        return False
    
    @classmethod
    def get_blocking_errors(cls, errors: List[ErrorDetail]) -> List[ErrorDetail]:
        """
        Get list of errors that would block dispatch.
        
        Args:
            errors: List of ErrorDetail objects from validation
            
        Returns:
            List of errors with blocking severity (error or critical)
        """
        return [error for error in errors if error.severity in cls.SEVERITY_BLOCKING]
    
    @classmethod
    def get_non_blocking_errors(cls, errors: List[ErrorDetail]) -> List[ErrorDetail]:
        """
        Get list of errors that would NOT block dispatch.
        
        Args:
            errors: List of ErrorDetail objects from validation
            
        Returns:
            List of errors with non-blocking severity (info or warning)
        """
        return [error for error in errors if error.severity in cls.SEVERITY_NON_BLOCKING]
