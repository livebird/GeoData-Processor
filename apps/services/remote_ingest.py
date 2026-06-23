"""
Remote ingest service for GDAL operations.

This module provides framework-agnostic remote file ingestion logic for downloading
files from remote URLs (HTTP, FTP, S3, etc.). It can be called by both Django REST
Framework views and Celery tasks.
"""

import os
import hashlib
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
import tempfile

try:
    import requests
except ImportError:
    requests = None

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None

from .error_catalog import ErrorCatalog, ErrorCode


@dataclass
class IngestResult:
    """Result of a remote ingest operation."""
    success: bool
    local_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_hash: Optional[str] = None
    error_message: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None
    downloaded_at: Optional[str] = None
    source_url: Optional[str] = None


@dataclass
class IngestOptions:
    """Options for remote ingest operations."""
    output_dir: Optional[str] = None
    preserve_filename: bool = True
    custom_filename: Optional[str] = None
    verify_checksum: bool = False
    expected_checksum: Optional[str] = None
    max_file_size: Optional[int] = None  # In bytes
    timeout: int = 300  # Download timeout in seconds
    chunk_size: int = 8192  # Download chunk size in bytes


class RemoteIngestService:
    """
    Framework-agnostic service for ingesting files from remote sources.
    
    This service handles downloading files from various remote sources including
    HTTP/HTTPS URLs, FTP URLs, and cloud storage (S3, Azure, GCS).
    """
    
    @staticmethod
    def _check_requests_available() -> None:
        """Check if requests library is available."""
        if requests is None:
            raise ImportError(
                "requests is required for HTTP/HTTPS ingest. "
                "Install it using: pip install requests"
            )
    
    @staticmethod
    def _calculate_file_hash(file_path: str, algorithm: str = "sha256") -> str:
        """
        Calculate the hash of a file.
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm to use (sha256, md5, etc.)
            
        Returns:
            Hexadecimal hash string
        """
        hash_func = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    
    @staticmethod
    def _get_filename_from_url(url: str) -> str:
        """
        Extract filename from URL.
        
        Args:
            url: URL to extract filename from
            
        Returns:
            Filename extracted from URL
        """
        parsed = urlparse(url)
        path = parsed.path
        filename = os.path.basename(path)
        
        if not filename or filename == "":
            # Generate a filename based on hash of URL
            url_hash = hashlib.md5(url.encode()).hexdigest()
            filename = f"remote_file_{url_hash}"
        
        return filename
    
    @staticmethod
    def ingest_from_http(
        url: str,
        options: Optional[IngestOptions] = None
    ) -> IngestResult:
        """
        Ingest a file from HTTP/HTTPS URL.
        
        Args:
            url: HTTP/HTTPS URL to download from
            options: Ingest options
            
        Returns:
            IngestResult with operation status
        """
        RemoteIngestService._check_requests_available()
        
        if options is None:
            options = IngestOptions()
        
        start_time = datetime.now()
        
        try:
            # Determine output path
            if options.output_dir:
                os.makedirs(options.output_dir, exist_ok=True)
            else:
                options.output_dir = tempfile.gettempdir()
            
            # Determine filename
            if options.custom_filename:
                filename = options.custom_filename
            elif options.preserve_filename:
                filename = RemoteIngestService._get_filename_from_url(url)
            else:
                url_hash = hashlib.md5(url.encode()).hexdigest()
                filename = f"remote_{url_hash}"
            
            local_path = os.path.join(options.output_dir, filename)
            
            # Stream download
            with requests.get(
                url,
                stream=True,
                timeout=options.timeout
            ) as response:
                response.raise_for_status()
                
                # Check content length against max size
                content_length = response.headers.get('content-length')
                if content_length and options.max_file_size:
                    if int(content_length) > options.max_file_size:
                        return IngestResult(
                            success=False,
                            error_message="File size exceeds maximum allowed size",
                            error_detail={
                                "content_length": int(content_length),
                                "max_size": options.max_file_size,
                            }
                        )
                
                # Download file
                downloaded_size = 0
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=options.chunk_size):
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # Check max file size during download
                        if options.max_file_size and downloaded_size > options.max_file_size:
                            os.remove(local_path)
                            return IngestResult(
                                success=False,
                                error_message="File size exceeds maximum allowed size during download",
                                error_detail={
                                    "downloaded_size": downloaded_size,
                                    "max_size": options.max_file_size,
                                }
                            )
            
            # Verify checksum if requested
            file_hash = None
            if options.verify_checksum:
                file_hash = RemoteIngestService._calculate_file_hash(local_path)
                if options.expected_checksum and file_hash != options.expected_checksum:
                    os.remove(local_path)
                    return IngestResult(
                        success=False,
                        error_message="File checksum verification failed",
                        error_detail={
                            "expected_checksum": options.expected_checksum,
                            "actual_checksum": file_hash,
                        }
                    )
            
            # Get file size
            file_size = os.path.getsize(local_path)
            
            downloaded_at = datetime.now().isoformat()
            
            return IngestResult(
                success=True,
                local_path=local_path,
                file_name=filename,
                file_size=file_size,
                file_hash=file_hash,
                downloaded_at=downloaded_at,
                source_url=url,
            )
            
        except requests.exceptions.RequestException as e:
            return IngestResult(
                success=False,
                error_message=f"HTTP download failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "url": url,
                }
            )
        except Exception as e:
            return IngestResult(
                success=False,
                error_message=f"Ingest failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "url": url,
                }
            )
    
    @staticmethod
    def ingest_from_s3(
        bucket: str,
        key: str,
        region: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        options: Optional[IngestOptions] = None
    ) -> IngestResult:
        """
        Ingest a file from AWS S3.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            region: AWS region
            access_key: AWS access key
            secret_key: AWS secret key
            options: Ingest options
            
        Returns:
            IngestResult with operation status
        """
        if boto3 is None:
            return IngestResult(
                success=False,
                error_message="boto3 is required for S3 ingest",
                error_detail={"error": "Missing boto3 library"}
            )
        
        if options is None:
            options = IngestOptions()
        
        start_time = datetime.now()
        
        try:
            # Create S3 client
            s3_client = boto3.client(
                's3',
                region_name=region or 'us-east-1',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            
            # Determine output path
            if options.output_dir:
                os.makedirs(options.output_dir, exist_ok=True)
            else:
                options.output_dir = tempfile.gettempdir()
            
            # Determine filename
            if options.custom_filename:
                filename = options.custom_filename
            elif options.preserve_filename:
                filename = os.path.basename(key)
            else:
                key_hash = hashlib.md5(key.encode()).hexdigest()
                filename = f"s3_{key_hash}"
            
            local_path = os.path.join(options.output_dir, filename)
            
            # Check file size before download
            try:
                head_response = s3_client.head_object(Bucket=bucket, Key=key)
                content_length = head_response.get('ContentLength', 0)
                
                if options.max_file_size and content_length > options.max_file_size:
                    return IngestResult(
                        success=False,
                        error_message="File size exceeds maximum allowed size",
                        error_detail={
                            "content_length": content_length,
                            "max_size": options.max_file_size,
                        }
                    )
            except ClientError as e:
                return IngestResult(
                    success=False,
                    error_message=f"Failed to get S3 object metadata: {str(e)}",
                    error_detail={"error_code": e.response['Error']['Code']}
                )
            
            # Download file
            s3_client.download_file(bucket, key, local_path)
            
            # Verify checksum if requested
            file_hash = None
            if options.verify_checksum:
                file_hash = RemoteIngestService._calculate_file_hash(local_path)
                if options.expected_checksum and file_hash != options.expected_checksum:
                    os.remove(local_path)
                    return IngestResult(
                        success=False,
                        error_message="File checksum verification failed",
                        error_detail={
                            "expected_checksum": options.expected_checksum,
                            "actual_checksum": file_hash,
                        }
                    )
            
            # Get file size
            file_size = os.path.getsize(local_path)
            
            downloaded_at = datetime.now().isoformat()
            source_url = f"s3://{bucket}/{key}"
            
            return IngestResult(
                success=True,
                local_path=local_path,
                file_name=filename,
                file_size=file_size,
                file_hash=file_hash,
                downloaded_at=downloaded_at,
                source_url=source_url,
            )
            
        except ClientError as e:
            return IngestResult(
                success=False,
                error_message=f"S3 ingest failed: {str(e)}",
                error_detail={"error_code": e.response['Error']['Code']}
            )
        except Exception as e:
            return IngestResult(
                success=False,
                error_message=f"S3 ingest failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                }
            )
    
    @staticmethod
    def ingest_from_url(
        url: str,
        options: Optional[IngestOptions] = None,
        **credentials
    ) -> IngestResult:
        """
        Ingest a file from a URL (auto-detect protocol).
        
        Args:
            url: URL to download from
            options: Ingest options
            **credentials: Additional credentials (access_key, secret_key, region, etc.)
            
        Returns:
            IngestResult with operation status
        """
        parsed = urlparse(url)
        
        if parsed.scheme in ('http', 'https'):
            return RemoteIngestService.ingest_from_http(url, options)
        elif parsed.scheme == 's3':
            # Parse S3 URL: s3://bucket/key
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
            return RemoteIngestService.ingest_from_s3(
                bucket, key,
                region=credentials.get('region'),
                access_key=credentials.get('access_key'),
                secret_key=credentials.get('secret_key'),
                options=options
            )
        else:
            return IngestResult(
                success=False,
                error_message=f"Unsupported URL scheme: {parsed.scheme}",
                error_detail={"url": url, "scheme": parsed.scheme}
            )
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Validate a URL format.
        
        Args:
            url: URL to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    @staticmethod
    def get_url_info(url: str) -> Dict[str, Any]:
        """
        Get information about a remote URL without downloading.
        
        Args:
            url: URL to get info for
            
        Returns:
            Dictionary with URL information
        """
        parsed = urlparse(url)
        
        info = {
            "url": url,
            "scheme": parsed.scheme,
            "netloc": parsed.netloc,
            "path": parsed.path,
            "filename": os.path.basename(parsed.path),
        }
        
        # Try to get file size for HTTP URLs
        if parsed.scheme in ('http', 'https'):
            try:
                RemoteIngestService._check_requests_available()
                response = requests.head(url, timeout=10)
                if response.status_code == 200:
                    info["content_length"] = response.headers.get('content-length')
                    info["content_type"] = response.headers.get('content-type')
                    info["accessible"] = True
                else:
                    info["accessible"] = False
                    info["status_code"] = response.status_code
            except Exception as e:
                info["accessible"] = False
                info["error"] = str(e)
        
        return info
