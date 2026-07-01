"""
MinIO storage helper for GeoData-Processor.

Usage:
    from converter.minio_storage import upload_to_minio

    minio_path = upload_to_minio(local_file_path, object_name)
    # Returns: "<bucket>/<object_name>"
"""

import os
import logging
from urllib.parse import quote

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_client():
    """Build and return a MinIO client using Django settings."""
    try:
        from minio import Minio
    except ImportError:
        raise ImportError(
            "The 'minio' package is not installed. "
            "Run: pip install minio>=7.0.0"
        )

    return Minio(
        endpoint=getattr(settings, 'MINIO_ENDPOINT', 'localhost:9000'),
        access_key=getattr(settings, 'MINIO_ACCESS_KEY', 'admin'),
        secret_key=getattr(settings, 'MINIO_SECRET_KEY', 'password123'),
        secure=getattr(settings, 'MINIO_SECURE', False),
    )


def get_minio_bucket_name():
    return getattr(settings, 'MINIO_BUCKET', 'kavanmineshshah')


def get_minio_object_prefix(task_id, kind='input'):
    return f"conversion-jobs/{task_id}/{kind}"


def build_public_object_url(object_name, bucket_name=None):
    bucket_name = bucket_name or get_minio_bucket_name()
    endpoint = getattr(settings, 'MINIO_ENDPOINT', 'localhost:9000').rstrip('/')
    scheme = 'https' if getattr(settings, 'MINIO_SECURE', False) else 'http'
    return f"{scheme}://{endpoint}/{bucket_name}/{quote(object_name)}"


def _ensure_bucket(client, bucket_name):
    """Create the bucket if it does not already exist."""
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        logger.info("[MinIO] Created bucket: %s", bucket_name)


def upload_to_minio(local_file_path, object_name=None):
    """
    Upload a local file to the configured MinIO bucket.

    Parameters
    ----------
    local_file_path : str
        Absolute path of the file on the local filesystem.
    object_name : str, optional
        Name / key for the object inside the bucket.
        Defaults to the basename of local_file_path.

    Returns
    -------
    str
        The MinIO object path in the form "<bucket>/<object_name>".

    Raises
    ------
    FileNotFoundError
        If local_file_path does not exist.
    Exception
        Propagates any MinIO SDK errors so callers can handle them.
    """
    if not os.path.isfile(local_file_path):
        raise FileNotFoundError(
            f"[MinIO] Local file not found: {local_file_path}"
        )

    if object_name is None:
        object_name = os.path.basename(local_file_path)

    bucket_name = get_minio_bucket_name()
    file_size = os.path.getsize(local_file_path)

    client = _get_client()
    _ensure_bucket(client, bucket_name)

    client.fput_object(
        bucket_name=bucket_name,
        object_name=object_name,
        file_path=local_file_path,
    )

    minio_path = f"{bucket_name}/{object_name}"
    logger.info(
        "[MinIO] Uploaded '%s' (%d bytes) -> %s",
        local_file_path, file_size, minio_path,
    )
    return minio_path


def upload_to_minio_best_effort(local_file_path, object_name=None):
    try:
        return upload_to_minio(local_file_path, object_name=object_name)
    except Exception as exc:
        logger.warning("[MinIO] Upload skipped for '%s': %s", local_file_path, exc)
        return None


def list_minio_objects(prefix="", bucket_name=None):
    client = _get_client()
    bucket_name = bucket_name or get_minio_bucket_name()
    if not client.bucket_exists(bucket_name):
        return []

    objects = []
    for obj in client.list_objects(bucket_name, prefix=prefix, recursive=True):
        objects.append(
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified,
                "url": build_public_object_url(obj.object_name, bucket_name=bucket_name),
            }
        )
    return objects
