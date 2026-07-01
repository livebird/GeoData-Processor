"""Bridge main converter jobs into the operator panel data model."""

import hashlib
import os

from django.utils import timezone

from .minio_storage import upload_to_minio_best_effort, get_minio_object_prefix

from .models import (
    ConversionInputFile,
    ConversionJob,
    DispatchedLayer,
    GeoFile,
    GeoProcessingJob,
    GeoProcessingJobLog,
    Workflow,
)

DEFAULT_WORKFLOWS = [
    {
        'code': 'file-conversion',
        'name': 'Vector/Raster Format Conversion',
        'description': (
            'Convert geospatial files between supported vector and raster formats '
            '(SHP, GeoJSON, GPKG, KML, CSV, GeoTIFF, PNG, and more).'
        ),
        'destination_type': 'download',
        'parameters_schema': {'output_format': 'string', 'target_crs': 'string'},
        'preview_enabled': False,
        'is_active': True,
    },
    {
        'code': 'coordinate-reprojection',
        'name': 'Coordinate Reference System Transform',
        'description': 'Reproject geospatial layers to a target EPSG coordinate reference system.',
        'destination_type': 'download',
        'parameters_schema': {'target_crs': 'string'},
        'preview_enabled': True,
        'is_active': True,
    },
    {
        'code': 'location-export',
        'name': 'Location Export Dispatch',
        'description': (
            'Place converted geospatial output at a map location and dispatch '
            'to the target destination platform.'
        ),
        'destination_type': 'feature_mapper',
        'parameters_schema': {'geojson_geom': 'string'},
        'preview_enabled': False,
        'is_active': True,
    },
]


def ensure_default_workflows():
    for spec in DEFAULT_WORKFLOWS:
        Workflow.objects.update_or_create(
            code=spec['code'],
            defaults={key: value for key, value in spec.items() if key != 'code'},
        )


def _conversion_idempotency_key(task_id):
    return f'conversion:{task_id}'


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _build_conversion_parameters(conversion_job):
    input_names = list(
        ConversionInputFile.objects.filter(job=conversion_job).values_list('original_name', flat=True)
    )
    return {
        'conversion_task_id': str(conversion_job.task_id),
        'input_format': conversion_job.input_format,
        'output_format': conversion_job.output_format,
        'input_files': input_names,
        'crs': conversion_job.crs,
    }


def get_operator_job_for_conversion(conversion_job):
    task_id = str(conversion_job.task_id)
    return GeoProcessingJob.objects.filter(
        idempotency_key=_conversion_idempotency_key(task_id)
    ).first()


def sync_conversion_job_started(conversion_job):
    try:
        ensure_default_workflows()
        task_id = str(conversion_job.task_id)
        job, created = GeoProcessingJob.objects.get_or_create(
            idempotency_key=_conversion_idempotency_key(task_id),
            defaults={
                'workflow_code': 'file-conversion',
                'status': 'processing',
                'parameters': _build_conversion_parameters(conversion_job),
                'progress_percent': 10,
                'started_at': timezone.now(),
            },
        )
        if not created and job.status in {'pending', 'processing'}:
            job.parameters = _build_conversion_parameters(conversion_job)
            job.progress_percent = max(job.progress_percent, 10)
            job.started_at = job.started_at or timezone.now()
            job.save(update_fields=['parameters', 'progress_percent', 'started_at', 'updated_at'])
        if created:
            GeoProcessingJobLog.objects.create(
                job=job,
                log_level='info',
                message=(
                    f'Conversion started: {conversion_job.input_format} '
                    f'→ {conversion_job.output_format}'
                ),
            )
        return job
    except Exception as exc:
        print(f'[WARN] operator sync start failed: {exc}')
        return None


def sync_conversion_job_completed(conversion_job, zip_path, output_files_count=0):
    try:
        ensure_default_workflows()
        job = get_operator_job_for_conversion(conversion_job) or sync_conversion_job_started(conversion_job)
        if not job:
            return None

        zip_path = os.path.abspath(zip_path)
        if not os.path.isfile(zip_path):
            raise FileNotFoundError(f'Converted output not found: {zip_path}')

        input_files = ConversionInputFile.objects.filter(job=conversion_job)
        first_input = input_files.first()
        input_name = first_input.original_name if first_input else os.path.basename(zip_path)
        zip_size = os.path.getsize(zip_path)
        zip_checksum = _file_sha256(zip_path)

        if not job.input_file_id:
            job.input_file = GeoFile.objects.create(
                original_file_name=input_name,
                source_type='upload',
                file_type=os.path.splitext(input_name)[1].lower() or '.zip',
                mime_type='application/octet-stream',
                storage_backend='local',
                storage_path=zip_path,
                size_bytes=zip_size,
                checksum_sha256=zip_checksum,
            )

        output_name = (
            f"{conversion_job.output_format or 'converted'}_"
            f"{str(conversion_job.task_id).replace('-', '')[:8]}.zip"
        )
        if not job.output_file_id:
            job.output_file = GeoFile.objects.create(
                original_file_name=output_name,
                source_type='local',
                file_type='.zip',
                mime_type='application/zip',
                storage_backend='local',
                storage_path=zip_path,
                size_bytes=zip_size,
                checksum_sha256=zip_checksum,
            )

        minio_object_name = f"{get_minio_object_prefix(conversion_job.task_id, 'output')}/{os.path.basename(zip_path)}"
        upload_to_minio_best_effort(zip_path, object_name=minio_object_name)

        job.status = 'completed'
        job.progress_percent = 100
        job.completed_at = timezone.now()
        job.error_message = None
        job.parameters = {
            **_build_conversion_parameters(conversion_job),
            'output_files_count': output_files_count,
            'download_url': conversion_job.download_url or f'/download/{conversion_job.task_id}/',
        }
        job.save()
        GeoProcessingJobLog.objects.create(
            job=job,
            log_level='info',
            message=f'Conversion completed with {output_files_count} output file(s).',
        )
        return job
    except Exception as exc:
        print(f'[WARN] operator sync complete failed: {exc}')
        return None


def sync_conversion_job_failed(conversion_job, error_message):
    try:
        job = get_operator_job_for_conversion(conversion_job) or sync_conversion_job_started(conversion_job)
        if not job:
            return None
        job.status = 'failed'
        job.error_message = (error_message or 'Conversion failed.')[:4000]
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
        GeoProcessingJobLog.objects.create(
            job=job,
            log_level='error',
            message=error_message or 'Conversion failed.',
        )
        return job
    except Exception as exc:
        print(f'[WARN] operator sync fail failed: {exc}')
        return None


def record_location_export_dispatch(location_export, conversion_job=None, geo_job=None):
    try:
        ensure_default_workflows()
        conv_task_id = location_export.conversion_job_task_id
        if conversion_job is None and conv_task_id:
            conversion_job = ConversionJob.objects.filter(task_id=conv_task_id).first()
        if geo_job is None and conv_task_id:
            geo_job = GeoProcessingJob.objects.filter(
                idempotency_key=_conversion_idempotency_key(conv_task_id)
            ).first()

        payload = {
            'location_export_task_id': str(location_export.task_id),
            'conversion_task_id': conv_task_id,
            'source_file_name': location_export.source_file_name,
            'source_kind': location_export.source_kind,
            'output_format': location_export.output_format,
            'exported_count': location_export.exported_count,
            'download_url': location_export.download_url,
            'geojson_geom': location_export.geojson_geom,
        }
        if conversion_job:
            payload['input_format'] = conversion_job.input_format
            payload['output_format'] = conversion_job.output_format or payload['output_format']

        layer, _ = DispatchedLayer.objects.update_or_create(
            target_system='location_export',
            target_layer_id=str(location_export.task_id),
            target_database_fingerprint=None,
            defaults={
                'job': geo_job,
                'status': 'success',
                'dispatched_at': timezone.now(),
                'payload_metadata': payload,
                'target_endpoint': location_export.download_url,
            },
        )
        return layer
    except Exception as exc:
        print(f'[WARN] location export dispatch failed: {exc}')
        return None
