"""
Dispatch service for GDAL operations.

This module provides framework-agnostic dispatch logic for sending converted
layers to external destinations (databases, cloud storage, etc.). It can be
called by both Django REST Framework views and Celery tasks.
"""

import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    psycopg2 = None

try:
    import pyodbc
except ImportError:
    pyodbc = None

from .error_catalog import ErrorCatalog, ErrorCode, ErrorDetail


@dataclass
class DestinationCredential:
    """Credentials for a destination."""
    id: str
    name: str
    destination_type: str  # 'postgresql', 'sqlserver', 's3', 'azure', 'gcs'
    connection_string: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    schema: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    is_active: bool = True


@dataclass
class DispatchResult:
    """Result of a dispatch operation."""
    success: bool
    destination_id: str
    destination_name: str
    dispatched_layers: Optional[List[str]] = None
    error_message: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None
    dispatched_at: Optional[str] = None


@dataclass
class DispatchedLayer:
    """Information about a dispatched layer."""
    id: str
    layer_name: str
    destination_id: str
    destination_name: str
    destination_type: str
    table_name: Optional[str] = None
    schema_name: Optional[str] = None
    s3_path: Optional[str] = None
    dispatched_at: Optional[str] = None
    status: str = "dispatched"  # dispatched, failed, pending
    feature_count: Optional[int] = None
    error_message: Optional[str] = None


class DispatchService:
    """
    Framework-agnostic service for dispatching layers to external destinations.
    
    This service handles dispatching converted geospatial layers to various
    destinations including databases (PostgreSQL, SQL Server) and cloud storage
    (S3, Azure Blob Storage, Google Cloud Storage).
    """
    
    @staticmethod
    def _check_postgresql_available() -> None:
        """Check if PostgreSQL driver is available."""
        if psycopg2 is None:
            raise ImportError(
                "psycopg2 is required for PostgreSQL dispatch. "
                "Install it using: pip install psycopg2-binary"
            )
    
    @staticmethod
    def _check_sqlserver_available() -> None:
        """Check if SQL Server driver is available."""
        if pyodbc is None:
            raise ImportError(
                "pyodbc is required for SQL Server dispatch. "
                "Install it using: pip install pyodbc"
            )
    
    @staticmethod
    def dispatch_to_postgresql(
        file_path: str,
        credential: DestinationCredential,
        layer_name: str,
        table_name: Optional[str] = None,
        schema: Optional[str] = None,
        overwrite: bool = False
    ) -> DispatchResult:
        """
        Dispatch a geospatial file to PostgreSQL database.
        
        Args:
            file_path: Path to the geospatial file
            credential: Destination credential
            layer_name: Name of the layer to dispatch
            table_name: Target table name (defaults to layer名称)
            schema: Target schema name
            overwrite: Whether to overwrite existing table
            
        Returns:
            DispatchResult with operation status
        """
        DispatchService._check_postgresql_available()
        
        if table_name is None:
            table_name = layer_name.lower().replace("-", "_")
        
        if schema is None:
            schema = credential.schema or "public"
        
        start_time = datetime.now()
        
        try:
            # Build connection string
            conn_params = {
                "host": credential.host or "localhost",
                "port": credential.port or 5432,
                "database": credential.database,
                "user": credential.username,
                "password": credential.password,
            }
            
            # Connect to database
            conn = psycopg2.connect(**conn_params)
            conn.autocommit = True
            cursor = conn.cursor()
            
            try:
                import geopandas as gpd
                
                # Read the layer
                gdf = gpd.read_file(file_path, layer=layer_name)
                
                # Drop table if overwrite is True
                if overwrite:
                    drop_query = sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table_name)
                    )
                    cursor.execute(drop_query)
                
                # Write to database
                gdf.to_postgis(
                    name=table_name,
                    con=conn,
                    schema=schema,
                    if_exists="fail" if not overwrite else "replace",
                    index=False,
                )
                
                dispatched_at = datetime.now().isoformat()
                
                return DispatchResult(
                    success=True,
                    destination_id=credential.id,
                    destination_name=credential.name,
                    dispatched_layers=[f"{schema}.{table_name}"],
                    dispatched_at=dispatched_at,
                )
                
            finally:
                cursor.close()
                conn.close()
                
        except ImportError as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message="geopandas is required for PostgreSQL dispatch",
                error_detail={"error": str(e)}
            )
        except Exception as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message=f"PostgreSQL dispatch failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "file_path": file_path,
                    "layer_name": layer_name,
                }
            )
    
    @staticmethod
    def dispatch_to_sqlserver(
        file_path: str,
        credential: DestinationCredential,
        layer_name: str,
        table_name: Optional[str] = None,
        schema: Optional[str] = None,
        overwrite: bool = False
    ) -> DispatchResult:
        """
        Dispatch a geospatial file to SQL Server database.
        
        Args:
            file_path: Path to the geospatial file
            credential: Destination credential
            layer_name: Name of the layer to dispatch
            table_name: Target table name
            schema: Target schema name
            overwrite: Whether to overwrite existing table
            
        Returns:
            DispatchResult with operation status
        """
        DispatchService._check_sqlserver_available()
        
        if table_name is None:
            table_name = layer_name.lower().replace("-", "_")
        
        if schema is None:
            schema = credential.schema or "dbo"
        
        start_time = datetime.now()
        
        try:
            # Build connection string
            driver = credential.connection_string or 'ODBC Driver 17 for SQL Server'
            server = credential.host or '.\\SQLEXPRESS'
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server};"
                f"DATABASE={credential.database};"
                f"UID={credential.username};"
                f"PWD={credential.password};"
            )
            
            # Connect to database
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            
            try:
                import geopandas as gpd
                
                # Read the layer
                gdf = gpd.read_file(file_path, layer=layer_name)
                
                # Drop table if overwrite is True
                if overwrite:
                    drop_query = f"DROP TABLE IF EXISTS {schema}.{table_name}"
                    cursor.execute(drop_query)
                    conn.commit()
                
                # Write to database using SQL Server geometry
                from sqlalchemy import create_engine
                from sqlalchemy.engine.url import URL
                
                engine_url = URL.create(
                    "mssql+pyodbc",
                    username=credential.username,
                    password=credential.password,
                    host=credential.host or ".\\SQLEXPRESS",
                    database=credential.database,
                    query={"driver": credential.connection_string or "ODBC Driver 17 for SQL Server"}
                )
                
                engine = create_engine(engine_url)
                
                gdf.to_sql(
                    name=table_name,
                    con=engine,
                    schema=schema,
                    if_exists="fail" if not overwrite else "replace",
                    index=False,
                    dtype={"geometry": "geometry"},
                )
                
                dispatched_at = datetime.now().isoformat()
                
                return DispatchResult(
                    success=True,
                    destination_id=credential.id,
                    destination_name=credential.name,
                    dispatched_layers=[f"{schema}.{table_name}"],
                    dispatched_at=dispatched_at,
                )
                
            finally:
                cursor.close()
                conn.close()
                
        except ImportError as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message="geopandas and sqlalchemy are required for SQL Server dispatch",
                error_detail={"error": str(e)}
            )
        except Exception as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message=f"SQL Server dispatch failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                    "file_path": file_path,
                    "layer_name": layer_name,
                }
            )
    
    @staticmethod
    def dispatch_to_s3(
        file_path: str,
        credential: DestinationCredential,
        bucket_name: Optional[str] = None,
        key_prefix: Optional[str] = None
    ) -> DispatchResult:
        """
        Dispatch a file to AWS S3.
        
        Args:
            file_path: Path to the file
            credential: Destination credential
            bucket_name: S3 bucket name
            key_prefix: Prefix for the S3 key
            
        Returns:
            DispatchResult with operation status
        """
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message="boto3 is required for S3 dispatch",
                error_detail={"error": "Missing boto3 library"}
            )
        
        if bucket_name is None:
            bucket_name = credential.bucket
        
        if key_prefix is None:
            key_prefix = ""
        
        try:
            # Create S3 client
            s3_client = boto3.client(
                's3',
                region_name=credential.region or 'us-east-1',
                aws_access_key_id=credential.access_key,
                aws_secret_access_key=credential.secret_key,
            )
            
            # Generate S3 key
            file_name = os.path.basename(file_path)
            s3_key = f"{key_prefix}/{file_name}" if key_prefix else file_name
            
            # Upload file
            s3_client.upload_file(file_path, bucket_name, s3_key)
            
            s3_path = f"s3://{bucket_name}/{s3_key}"
            dispatched_at = datetime.now().isoformat()
            
            return DispatchResult(
                success=True,
                destination_id=credential.id,
                destination_name=credential.name,
                dispatched_layers=[s3_path],
                dispatched_at=dispatched_at,
            )
            
        except ClientError as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message=f"S3 dispatch failed: {str(e)}",
                error_detail={"error_code": e.response['Error']['Code']}
            )
        except Exception as e:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message=f"S3 dispatch failed: {str(e)}",
                error_detail={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                }
            )
    
    @staticmethod
    def dispatch(
        file_path: str,
        credential: DestinationCredential,
        layer_name: Optional[str] = None,
        validation_errors: Optional[List[ErrorDetail]] = None,
        **kwargs
    ) -> DispatchResult:
        """
        Dispatch a file to the specified destination.
        
        Implements FR-VAL-004: Blocks dispatch if error or critical severity issues exist.
        Implements FR-VAL-005: Allows processing past info and warning.
        
        Args:
            file_path: Path to the file
            credential: Destination credential
            layer_name: Name of the layer (for vector files)
            validation_errors: Optional list of validation errors to check before dispatch
            **kwargs: Additional dispatch parameters
            
        Returns:
            DispatchResult with operation status
        """
        # Check validation errors for blocking severity (FR-VAL-004)
        if validation_errors:
            if ErrorCatalog.should_block_dispatch(validation_errors):
                blocking_errors = ErrorCatalog.get_blocking_errors(validation_errors)
                return DispatchResult(
                    success=False,
                    destination_id=credential.id,
                    destination_name=credential.name,
                    error_message="Dispatch blocked due to validation errors",
                    error_detail={
                        "blocking_errors": [e.to_dict() for e in blocking_errors],
                        "non_blocking_errors": [e.to_dict() for e in ErrorCatalog.get_non_blocking_errors(validation_errors)],
                    }
                )
        
        destination_type = credential.destination_type.lower()
        
        if destination_type == "postgresql":
            return DispatchService.dispatch_to_postgresql(
                file_path, credential, layer_name, **kwargs
            )
        elif destination_type == "sqlserver":
            return DispatchService.dispatch_to_sqlserver(
                file_path, credential, layer_name, **kwargs
            )
        elif destination_type == "s3":
            return DispatchService.dispatch_to_s3(
                file_path, credential, **kwargs
            )
        else:
            return DispatchResult(
                success=False,
                destination_id=credential.id,
                destination_name=credential.name,
                error_message=f"Unsupported destination type: {destination_type}",
                error_detail={"destination_type": destination_type}
            )
    
    @staticmethod
    def validate_credential(credential: DestinationCredential) -> bool:
        """
        Validate a destination credential.
        
        Args:
            credential: Destination credential to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not credential.id or not credential.name:
            return False
        
        if not credential.destination_type:
            return False
        
        destination_type = credential.destination_type.lower()
        
        if destination_type == "postgresql":
            if not credential.database or not credential.username:
                return False
        elif destination_type == "sqlserver":
            if not credential.database or not credential.username:
                return False
        elif destination_type == "s3":
            if not credential.bucket:
                return False
        
        return True
    
    @staticmethod
    def create_dispatched_layer(
        layer_id: str,
        layer_name: str,
        credential: DestinationCredential,
        table_name: Optional[str] = None,
        feature_count: Optional[int] = None
    ) -> DispatchedLayer:
        """
        Create a DispatchedLayer record.
        
        Args:
            layer_id: Unique ID for the dispatched layer
            layer_name: Name of the layer
            credential: Destination credential
            table_name: Target table name
            feature_count: Number of features in the layer
            
        Returns:
            DispatchedLayer object
        """
        return DispatchedLayer(
            id=layer_id,
            layer_name=layer_name,
            destination_id=credential.id,
            destination_name=credential.name,
            destination_type=credential.destination_type,
            table_name=table_name,
            schema_name=credential.schema,
            dispatched_at=datetime.now().isoformat(),
            status="dispatched",
            feature_count=feature_count,
        )
