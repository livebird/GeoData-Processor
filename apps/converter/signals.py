"""
Best-effort signal handlers for conversion and GIS metadata audit logging.

These handlers must never block the actual conversion workflow. Audit tables can
lag behind schema changes, so every handler catches logging failures and reports
an ASCII-safe warning for Windows consoles.
"""

import json
import uuid
from datetime import datetime

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditLog, BatchTableDetails, ConversionJob, GeoFile, GeoFileLayer, DispatchedLayer


SYSTEM_ACTOR_ID = 0
DEFAULT_ORG_ID = uuid.UUID('232ce34d-4db5-40c1-9b3d-38940e959702')


def _safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"))


def _json_details(details):
    return json.dumps(details, default=str) if details else "{}"


def _create_audit_log(*, org_id, actor_type, actor_id, action, resource_type, resource_id, details=None, ip_address="127.0.0.1"):
    return AuditLog.objects.create(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id or SYSTEM_ACTOR_ID,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=details or {},
        ip_address=ip_address or "127.0.0.1",
    )


def _create_batch_details(*, org_id, actor_type, actor_id, action, resource_type, resource_id, name, table_name, codename, details=None, user_agent=""):
    return BatchTableDetails.objects.create(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id or SYSTEM_ACTOR_ID,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=_json_details(details),
        name=name,
        table_name=table_name,
        actual_table_name=table_name,
        codename=codename,
        void=False,
        ondelete="CASCADE",
        secret="",
        app_label="converter",
        validation_domainid="1",
        content_type=resource_type.lower(),
        user_agent=user_agent or "",
    )


@receiver(post_save, sender=ConversionJob)
def log_conversion_job(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        details = {
            "task_id": str(instance.task_id),
            "status": instance.status,
            "input_format": instance.input_format,
            "output_format": instance.output_format,
            "upload_files_count": instance.upload_files_count,
            "output_files_count": instance.output_files_count,
            "created_at": instance.created_at.isoformat(),
            "ip_address": instance.ip_address,
        }
        _create_audit_log(
            org_id=DEFAULT_ORG_ID,
            actor_type="SYSTEM",
            actor_id=SYSTEM_ACTOR_ID,
            action="CREATE",
            resource_type="FILE_CONVERSION",
            resource_id=instance.task_id,
            details=details,
            ip_address=instance.ip_address,
        )
        _create_batch_details(
            org_id=DEFAULT_ORG_ID,
            actor_type="SYSTEM",
            actor_id=SYSTEM_ACTOR_ID,
            action="CREATE",
            resource_type="FILE_CONVERSION",
            resource_id=instance.task_id,
            name=f"Conversion {instance.task_id}",
            table_name="conversion_jobs",
            codename="convert_file",
            details={
                "conversion": "file_format_conversion",
                "input_format": instance.input_format,
                "output_format": instance.output_format,
                "timestamp": datetime.now().isoformat(),
            },
            user_agent=instance.user_agent,
        )
        _safe_print(f"[OK] Logged conversion job {instance.task_id}")
    except Exception as exc:
        _safe_print(f"[WARN] Error logging conversion job: {exc}")


@receiver(post_save, sender=GeoFileLayer)
def log_geo_layer(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        details = {
            "layer_name": instance.layer_name,
            "geometry_type": instance.geometry_type,
            "feature_count": instance.feature_count,
            "bbox": instance.bbox,
            "has_z": instance.has_z,
            "has_m": instance.has_m,
        }
        _create_audit_log(
            org_id=DEFAULT_ORG_ID,
            actor_type="SYSTEM",
            actor_id=SYSTEM_ACTOR_ID,
            action="CREATE",
            resource_type="GEO_LAYER",
            resource_id=instance.id,
            details=details,
        )
        _create_batch_details(
            org_id=DEFAULT_ORG_ID,
            actor_type="SYSTEM",
            actor_id=SYSTEM_ACTOR_ID,
            action="CREATE",
            resource_type="GEO_LAYER",
            resource_id=instance.id,
            name=instance.layer_name or "Geo Layer",
            table_name="geo_file_layers",
            codename="geo_layer",
            details=details,
        )
        
        # Also create a DispatchedLayer record for the dispatched layers table
        try:
            DispatchedLayer.objects.create(
                target_layer_id=str(instance.id),
                target_system='layer_definition',
                status='discovered',
                dispatched_at=datetime.now(),
                payload_metadata={
                    'layer_name': instance.layer_name,
                    'geometry_type': instance.geometry_type,
                    'feature_count': instance.feature_count,
                    'source_crs_epsg': instance.source_crs_epsg,
                }
            )
        except Exception as dispatch_exc:
            _safe_print(f"[WARN] Error creating dispatched layer for geo layer: {dispatch_exc}")
        
        _safe_print(f"[OK] Logged geo layer {instance.layer_name}")
    except Exception as exc:
        _safe_print(f"[WARN] Error logging geo layer: {exc}")


@receiver(post_save, sender=GeoFile)
def log_geo_file(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        actor_id_str = instance.uploaded_by_id or str(SYSTEM_ACTOR_ID)
        actor_id_int = SYSTEM_ACTOR_ID
        if instance.uploaded_by_id and instance.uploaded_by:
            actor_id_int = instance.uploaded_by.pk
            
        details = {
            "filename": instance.original_file_name,
            "file_type": instance.file_type,
            "size_bytes": instance.size_bytes,
            "checksum": instance.checksum_sha256,
        }
        _create_audit_log(
            org_id=DEFAULT_ORG_ID,
            actor_type="USER",
            actor_id=actor_id_str,
            action="CREATE",
            resource_type="GEO_FILE",
            resource_id=instance.id,
            details=details,
        )
        _create_batch_details(
            org_id=DEFAULT_ORG_ID,
            actor_type="USER",
            actor_id=actor_id_int,
            action="CREATE",
            resource_type="GEO_FILE",
            resource_id=instance.id,
            name=instance.original_file_name or "Geo File",
            table_name="geo_files",
            codename="geo_file",
            details=details,
        )
        _safe_print(f"[OK] Logged geo file {instance.original_file_name}")
    except Exception as exc:
        _safe_print(f"[WARN] Error logging geo file: {exc}")


def log_audit_trail(org_id, actor_type, actor_id, action, resource_type, resource_id, details=None, ip_address="127.0.0.1"):
    try:
        return _create_audit_log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
    except Exception as exc:
        _safe_print(f"[WARN] Error logging audit trail: {exc}")
        return None


def log_batch_details(
    org_id,
    actor_type,
    actor_id,
    action,
    resource_type,
    resource_id,
    name,
    table_name,
    codename,
    details=None,
    user_agent="",
    **kwargs,
):
    try:
        return _create_batch_details(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            name=name,
            table_name=table_name,
            codename=codename,
            details=details,
            user_agent=user_agent,
        )
    except Exception as exc:
        _safe_print(f"[WARN] Error logging batch details: {exc}")
        return None
