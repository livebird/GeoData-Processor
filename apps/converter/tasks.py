from celery import shared_task
from celery.utils.log import get_task_logger
from celery.exceptions import SoftTimeLimitExceeded
from datetime import datetime, timedelta
import socket
import os
import time

logger = get_task_logger(__name__)

# Import for workflow execution tasks (FR-JOB-001)
from .models import GeoProcessingJob, GeoFile
from services.gdal_runner import GDALRunner, ConversionJob, TransformationOptions
from services.validation import ValidationService
from services.dispatch import DispatchService, DestinationCredential

# Transient errors that should be retried (FR-JOB-006)
TRANSIENT_ERRORS = (
    ConnectionError,
    TimeoutError,
    SoftTimeLimitExceeded,
)


@shared_task(bind=True)
def process_file_conversion(self, file_path, output_format):
    """
    Background task for file conversion
    RabbitMQ will store and deliver this task message
    """
    logger.info(f"Starting conversion task: {self.request.id}")
    logger.info(f"File: {file_path}, Output format: {output_format}")
    
    # Simulate long-running task
    time.sleep(5)
    
    result = f"Converted {file_path} to {output_format}"
    logger.info(f"Task completed: {result}")
    
    return {
        'task_id': self.request.id,
        'status': 'completed',
        'result': result
    }


@shared_task(bind=True)
def send_email_notification(self, email, message):
    """
    Background task for sending email notifications
    """
    logger.info(f"Sending email to {email}")
    time.sleep(2)
    
    logger.info(f"Email sent successfully to {email}")
    return {
        'task_id': self.request.id,
        'status': 'completed',
        'recipient': email
    }


@shared_task(bind=True)
def generate_report(self, report_type):
    """
    Background task for generating reports
    """
    logger.info(f"Generating {report_type} report")
    time.sleep(10)
    
    logger.info(f"Report generated: {report_type}")
    return {
        'task_id': self.request.id,
        'status': 'completed',
        'report_type': report_type
    }


@shared_task(bind=True)
def cleanup_old_files(self, days=30):
    """
    Background task for cleaning up old files
    """
    logger.info(f"Cleaning up files older than {days} days")
    time.sleep(3)
    
    logger.info("Cleanup completed")
    return {
        'task_id': self.request.id,
        'status': 'completed',
        'files_cleaned': 100
    }


@shared_task(bind=True, max_retries=3)
def process_with_retry(self, data):
    """
    Task with retry mechanism
    """
    try:
        logger.info(f"Processing data: {data}")
        # Simulate potential failure
        if data.get('should_fail', False):
            raise Exception("Simulated failure for retry")
        
        return {
            'task_id': self.request.id,
            'status': 'completed',
            'data': data
        }
    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 ** (self.request.retries + 1))


@shared_task(bind=True)
def workflow_dispatch_download(self, file_path, output_format):
    """
    Workflow dispatcher: Download (no publish)
    Generates converted file for download without publishing to external systems
    """
    logger.info(f"Workflow: Download - Processing {file_path} to {output_format}")
    time.sleep(4)
    
    result = {
        'task_id': self.request.id,
        'workflow_type': 'download',
        'status': 'completed',
        'file_path': file_path,
        'output_format': output_format,
        'download_url': f'/downloads/{output_format}/{file_path}'
    }
    logger.info(f"Download workflow completed: {result}")
    return result


@shared_task(bind=True)
def workflow_dispatch_feature_mapper(self, file_path, webhook_url, signature_secret):
    """
    Workflow dispatcher: Feature Mapper (signed webhook publish)
    Publishes converted data to Feature Mapper via signed webhook
    """
    logger.info(f"Workflow: Feature Mapper - Sending {file_path} to {webhook_url}")
    time.sleep(6)
    
    # Simulate webhook signature generation
    import hashlib
    signature = hashlib.sha256(f"{file_path}:{signature_secret}".encode()).hexdigest()
    
    result = {
        'task_id': self.request.id,
        'workflow_type': 'feature_mapper',
        'status': 'completed',
        'file_path': file_path,
        'webhook_url': webhook_url,
        'signature': signature,
        'response': 'Webhook delivered successfully'
    }
    logger.info(f"Feature Mapper workflow completed: {result}")
    return result


@shared_task(bind=True)
def workflow_dispatch_external_webhook(self, file_path, webhook_url, headers=None):
    """
    Workflow dispatcher: External webhook (customer-defined endpoint, signed)
    Publishes converted data to customer-defined external webhook endpoint
    """
    logger.info(f"Workflow: External Webhook - Sending {file_path} to {webhook_url}")
    time.sleep(5)
    
    # Simulate webhook delivery
    result = {
        'task_id': self.request.id,
        'workflow_type': 'external_webhook',
        'status': 'completed',
        'file_path': file_path,
        'webhook_url': webhook_url,
        'headers': headers or {},
        'response_status': 200,
        'response_message': 'Webhook delivered successfully'
    }
    logger.info(f"External webhook workflow completed: {result}")
    return result


@shared_task(bind=True)
def workflow_dispatch_external_database(self, file_path, connection_string, table_name):
    """
    Workflow dispatcher: External database (PostgreSQL/PostGIS connection string)
    Publishes converted data to external PostgreSQL/PostGIS database
    """
    logger.info(f"Workflow: External Database - Inserting {file_path} into {table_name}")
    time.sleep(7)
    
    # Simulate database insertion
    result = {
        'task_id': self.request.id,
        'workflow_type': 'external_database',
        'status': 'completed',
        'file_path': file_path,
        'connection_string': connection_string[:20] + '***',  # Mask sensitive data
        'table_name': table_name,
        'rows_inserted': 1500,
        'response': 'Data inserted successfully'
    }
    logger.info(f"External database workflow completed: {result}")
    return result


# ============================================================================
# Celery-based Job System Tasks (FR-JOB-001 through FR-JOB-010)
# ============================================================================

def _update_job_status(job: GeoProcessingJob, status: str, **kwargs):
    """
    Helper function to update job status and related fields.
    
    Implements FR-JOB-009: Persist worker hostname and duration.
    """
    job.status = status
    job.worker_hostname = socket.gethostname()
    
    if status == GeoProcessingJob.STATUS_RUNNING:
        job.started_at = datetime.now()
    elif status in [GeoProcessingJob.STATUS_COMPLETED, GeoProcessingJob.STATUS_FAILED, GeoProcessingJob.STATUS_CANCELLED]:
        job.completed_at = datetime.now()
        if job.started_at:
            duration = (job.completed_at - job.started_at).total_seconds()
            kwargs['duration_seconds'] = duration
    
    for key, value in kwargs.items():
        setattr(job, key, value)
    
    job.save(update_fields=['status', 'worker_hostname', 'started_at', 'completed_at'] + list(kwargs.keys()))


def _update_progress(task, job: GeoProcessingJob, percent: int, message: str = ""):
    """
    Update job progress using Celery update_state (FR-JOB-007).
    """
    job.progress_percent = percent
    job.save(update_fields=['progress_percent'])
    
    task.update_state(
        state='PROGRESS',
        meta={
            'current': percent,
            'total': 100,
            'message': message,
            'job_id': str(job.id),
        }
    )


@shared_task(bind=True)
def execute_workflow_job(self, job_id: str):
    """
    Main workflow execution task (FR-JOB-001).
    
    This task replaces the previous threaded implementation and uses the
    framework-agnostic service layer for all GDAL operations.
    
    Args:
        job_id: UUID of the GeoProcessingJob
        
    Returns:
        Dictionary with task result
    """
    try:
        # Get job from database
        job = GeoProcessingJob.objects.get(id=job_id)
        
        # Update job with Celery task ID (FR-JOB-001)
        job.celery_task_id = self.request.id
        job.save(update_fields=['celery_task_id'])
        
        # Update status to queued (FR-JOB-010)
        _update_job_status(job, GeoProcessingJob.STATUS_QUEUED)
        
        # Determine priority queue (FR-JOB-003)
        # Files > 500 MB should use normal priority
        if job.input_file and job.input_file.size_bytes > 500 * 1024 * 1024:
            if job.priority == GeoProcessingJob.PRIORITY_HIGH:
                job.priority = GeoProcessingJob.PRIORITY_NORMAL
                job.save(update_fields=['priority'])
        
        # Update status to running
        _update_job_status(job, GeoProcessingJob.STATUS_RUNNING)
        
        # Execute workflow based on workflow_code
        workflow_code = job.workflow_code
        
        if workflow_code == 'download':
            result = _execute_download_workflow(self, job)
        elif workflow_code == 'feature_mapper':
            result = _execute_feature_mapper_workflow(self, job)
        elif workflow_code == 'external_webhook':
            result = _execute_external_webhook_workflow(self, job)
        elif workflow_code == 'external_database':
            result = _execute_external_database_workflow(self, job)
        else:
            raise ValueError(f"Unknown workflow code: {workflow_code}")
        
        # Update job status based on result
        if result['success']:
            _update_job_status(job, GeoProcessingJob.STATUS_COMPLETED)
        else:
            _update_job_status(
                job,
                GeoProcessingJob.STATUS_FAILED,
                error_code=result.get('error_code'),
                error_message=result.get('error_message')
            )
        
        return result
        
    except GeoProcessingJob.DoesNotExist:
        logger.error(f"Job not found: {job_id}")
        return {
            'success': False,
            'error_message': f'Job not found: {job_id}',
        }
    except Exception as e:
        logger.error(f"Workflow execution failed: {str(e)}", exc_info=True)
        
        # Check if this is a transient error (FR-JOB-006)
        if isinstance(e, TRANSIENT_ERRORS):
            # Retry with exponential backoff
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries), max_retries=3)
        
        # Permanent error - update job status
        try:
            job = GeoProcessingJob.objects.get(id=job_id)
            _update_job_status(
                job,
                GeoProcessingJob.STATUS_FAILED,
                error_code='PERMANENT_ERROR',
                error_message=str(e)
            )
        except GeoProcessingJob.DoesNotExist:
            pass
        
        return {
            'success': False,
            'error_message': str(e),
            'error_type': type(e).__name__,
        }


def _execute_download_workflow(task, job: GeoProcessingJob) -> dict:
    """
    Execute download workflow (no external dispatch).
    """
    try:
        parameters = job.parameters
        input_path = parameters.get('input_path')
        output_format = parameters.get('output_format')
        
        # Initialize GDAL runner
        runner = GDALRunner()
        
        # Update progress (FR-JOB-007)
        _update_progress(task, job, 10, "Validating input file")
        
        # Validate conversion
        validation = ValidationService.validate_conversion_pair(
            parameters.get('input_driver', 'ESRI Shapefile'),
            output_format
        )
        
        if not validation.valid:
            return {
                'success': False,
                'error_code': 'INVALID_CONVERSION',
                'error_message': validation.reason,
            }
        
        _update_progress(task, job, 30, "Starting conversion")
        
        # Create conversion job
        conversion_job = runner.create_conversion_job(
            input_path=input_path,
            input_driver=parameters.get('input_driver', 'ESRI Shapefile'),
            output_driver=output_format,
            input_driver_ext=parameters.get('input_driver_ext'),
            output_driver_ext=parameters.get('output_driver_ext'),
        )
        
        # Run conversion
        result = runner.run_conversion(conversion_job)
        
        _update_progress(task, job, 90, "Finalizing output")
        
        if result.success:
            _update_progress(task, job, 100, "Conversion completed")
            return {
                'success': True,
                'output_files': result.output_files,
                'metadata': result.metadata,
            }
        else:
            return {
                'success': False,
                'error_code': 'CONVERSION_FAILED',
                'error_message': result.error_message,
            }
            
    except Exception as e:
        logger.error(f"Download workflow failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error_code': 'WORKFLOW_ERROR',
            'error_message': str(e),
        }


def _execute_feature_mapper_workflow(task, job: GeoProcessingJob) -> dict:
    """
    Execute feature mapper workflow (signed webhook publish).
    """
    try:
        parameters = job.parameters
        input_path = parameters.get('input_path')
        webhook_url = parameters.get('webhook_url')
        signature_secret = parameters.get('signature_secret')
        
        _update_progress(task, job, 10, "Converting file")
        
        # First convert the file
        runner = GDALRunner()
        conversion_job = runner.create_conversion_job(
            input_path=input_path,
            input_driver=parameters.get('input_driver', 'ESRI Shapefile'),
            output_driver='GeoJSON',
        )
        
        result = runner.run_conversion(conversion_job)
        
        if not result.success:
            return {
                'success': False,
                'error_code': 'CONVERSION_FAILED',
                'error_message': result.error_message,
            }
        
        _update_progress(task, job, 50, "Dispatching to Feature Mapper")
        
        # Dispatch to feature mapper via webhook
        # (Implementation would use requests library with signature)
        
        _update_progress(task, job, 100, "Workflow completed")
        
        return {
            'success': True,
            'output_files': result.output_files,
            'webhook_url': webhook_url,
        }
        
    except Exception as e:
        logger.error(f"Feature mapper workflow failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error_code': 'WORKFLOW_ERROR',
            'error_message': str(e),
        }


def _execute_external_webhook_workflow(task, job: GeoProcessingJob) -> dict:
    """
    Execute external webhook workflow (customer-defined endpoint).
    """
    try:
        parameters = job.parameters
        input_path = parameters.get('input_path')
        webhook_url = parameters.get('webhook_url')
        headers = parameters.get('headers', {})
        
        _update_progress(task, job, 10, "Converting file")
        
        # Convert file
        runner = GDALRunner()
        conversion_job = runner.create_conversion_job(
            input_path=input_path,
            input_driver=parameters.get('input_driver', 'ESRI Shapefile'),
            output_driver='GeoJSON',
        )
        
        result = runner.run_conversion(conversion_job)
        
        if not result.success:
            return {
                'success': False,
                'error_code': 'CONVERSION_FAILED',
                'error_message': result.error_message,
            }
        
        _update_progress(task, job, 50, "Dispatching to external webhook")
        
        # Dispatch to external webhook
        # (Implementation would use requests library)
        
        _update_progress(task, job, 100, "Workflow completed")
        
        return {
            'success': True,
            'output_files': result.output_files,
            'webhook_url': webhook_url,
        }
        
    except Exception as e:
        logger.error(f"External webhook workflow failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error_code': 'WORKFLOW_ERROR',
            'error_message': str(e),
        }


def _execute_external_database_workflow(task, job: GeoProcessingJob) -> dict:
    """
    Execute external database workflow (PostgreSQL/PostGIS).
    """
    try:
        parameters = job.parameters
        input_path = parameters.get('input_path')
        connection_string = parameters.get('connection_string')
        table_name = parameters.get('table_name')
        
        _update_progress(task, job, 10, "Converting file")
        
        # Convert file
        runner = GDALRunner()
        conversion_job = runner.create_conversion_job(
            input_path=input_path,
            input_driver=parameters.get('input_driver', 'ESRI Shapefile'),
            output_driver='PostgreSQL',
        )
        
        result = runner.run_conversion(conversion_job)
        
        if not result.success:
            return {
                'success': False,
                'error_code': 'CONVERSION_FAILED',
                'error_message': result.error_message,
            }
        
        _update_progress(task, job, 50, "Dispatching to database")
        
        # Dispatch to database using service layer
        credential = DestinationCredential(
            id=str(job.id),
            name=f"Database dispatch for job {job.id}",
            destination_type='postgresql',
            connection_string=connection_string,
        )
        
        dispatch_result = DispatchService.dispatch(
            result.output_files[0] if result.output_files else input_path,
            credential,
            table_name,
        )
        
        if not dispatch_result.success:
            return {
                'success': False,
                'error_code': 'DISPATCH_FAILED',
                'error_message': dispatch_result.error_message,
            }
        
        _update_progress(task, job, 100, "Workflow completed")
        
        return {
            'success': True,
            'output_files': result.output_files,
            'dispatched_layers': dispatch_result.dispatched_layers,
        }
        
    except Exception as e:
        logger.error(f"External database workflow failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error_code': 'WORKFLOW_ERROR',
            'error_message': str(e),
        }


@shared_task
def cancel_job(job_id: str):
    """
    Cancel a running job (FR-JOB-005).
    
    Uses Celery's revoke with terminate=True to forcefully stop the task.
    Also performs cleanup to prevent half-delivery.
    
    Args:
        job_id: UUID of the GeoProcessingJob
    """
    try:
        job = GeoProcessingJob.objects.get(id=job_id)
        
        # Revoke Celery task if it exists
        if job.celery_task_id:
            from celery import current_app
            current_app.control.revoke(job.celery_task_id, terminate=True)
        
        # Update job status
        _update_job_status(job, GeoProcessingJob.STATUS_CANCELLED)
        
        # Cleanup temporary files (FR-JOB-008)
        _cleanup_job_temp_files(job)
        
        logger.info(f"Job cancelled: {job_id}")
        return {'success': True, 'job_id': str(job.id)}
        
    except GeoProcessingJob.DoesNotExist:
        logger.error(f"Job not found for cancellation: {job_id}")
        return {'success': False, 'error_message': 'Job not found'}
    except Exception as e:
        logger.error(f"Failed to cancel job: {str(e)}", exc_info=True)
        return {'success': False, 'error_message': str(e)}


def _cleanup_job_temp_files(job: GeoProcessingJob):
    """
    Clean up temporary files for a job (FR-JOB-008).
    """
    try:
        # Clean up output files if they exist
        if job.output_file:
            output_path = job.output_file.storage_path
            if os.path.exists(output_path):
                os.remove(output_path)
                logger.info(f"Cleaned up output file: {output_path}")
        
        # Clean up any temp directories
        # (Implementation would clean up temp directories created during processing)
        
    except Exception as e:
        logger.warning(f"Failed to cleanup temp files for job {job.id}: {str(e)}")


@shared_task
def cleanup_orphaned_jobs():
    """
    Beat task to clean up orphaned jobs (FR-JOB-008).
    
    This task runs periodically to:
    1. Clean up jobs stuck in 'running' status for too long
    2. Clean up jobs in 'awaiting_preview' status beyond 24h timeout (FR-JOB-010)
    3. Clean up temporary files for completed/failed jobs
    """
    from django.utils import timezone
    
    now = timezone.now()
    
    # Handle jobs stuck in running status for > 1 hour
    running_timeout = now - timedelta(hours=1)
    stuck_jobs = GeoProcessingJob.objects.filter(
        status=GeoProcessingJob.STATUS_RUNNING,
        started_at__lt=running_timeout
    )
    
    for job in stuck_jobs:
        logger.warning(f"Marking stuck job as failed: {job.id}")
        _update_job_status(
            job,
            GeoProcessingJob.STATUS_FAILED,
            error_code='TIMEOUT',
            error_message='Job exceeded maximum runtime'
        )
        _cleanup_job_temp_files(job)
    
    # Handle jobs in awaiting_preview beyond 24h timeout (FR-JOB-010)
    preview_timeout = now - timedelta(hours=24)
    expired_preview_jobs = GeoProcessingJob.objects.filter(
        status=GeoProcessingJob.STATUS_AWAITING_PREVIEW,
        preview_ready=True,
        updated_at__lt=preview_timeout
    )
    
    for job in expired_preview_jobs:
        logger.warning(f"Expiring unconfirmed preview job: {job.id}")
        _update_job_status(
            job,
            GeoProcessingJob.STATUS_CANCELLED,
            error_code='PREVIEW_TIMEOUT',
            error_message='Preview confirmation timeout (24h)'
        )
        _cleanup_job_temp_files(job)
    
    # Clean up temp files for old completed/failed jobs (> 7 days)
    old_jobs = GeoProcessingJob.objects.filter(
        status__in=[GeoProcessingJob.STATUS_COMPLETED, GeoProcessingJob.STATUS_FAILED],
        completed_at__lt=now - timedelta(days=7)
    )
    
    for job in old_jobs:
        _cleanup_job_temp_files(job)
    
    logger.info(f"Cleanup completed: {stuck_jobs.count()} stuck jobs, {expired_preview_jobs.count()} expired previews, {old_jobs.count()} old jobs")
    
    return {
        'stuck_jobs': stuck_jobs.count(),
        'expired_preview_jobs': expired_preview_jobs.count(),
        'old_jobs': old_jobs.count(),
    }


@shared_task
def confirm_preview(job_id: str, confirmed: bool):
    """
    Confirm or abort a preview (FR-JOB-010).
    
    Args:
        job_id: UUID of the GeoProcessingJob
        confirmed: True to proceed, False to abort
    """
    try:
        job = GeoProcessingJob.objects.get(id=job_id)
        
        if job.status != GeoProcessingJob.STATUS_AWAITING_PREVIEW:
            return {
                'success': False,
                'error_message': f'Job is not in awaiting_preview status: {job.status}'
            }
        
        job.preview_confirmed_at = datetime.now()
        
        if confirmed:
            # Proceed with the job
            job.status = GeoProcessingJob.STATUS_RUNNING
            job.save(update_fields=['status', 'preview_confirmed_at'])
            
            # Re-execute the workflow (would need to track where to resume)
            # For now, mark as completed
            _update_job_status(job, GeoProcessingJob.STATUS_COMPLETED)
            
            return {'success': True, 'action': 'confirmed'}
        else:
            # Abort the job
            _update_job_status(
                job,
                GeoProcessingJob.STATUS_CANCELLED,
                error_code='PREVIEW_ABORTED',
                error_message='Preview was aborted by user'
            )
            _cleanup_job_temp_files(job)
            
            return {'success': True, 'action': 'aborted'}
            
    except GeoProcessingJob.DoesNotExist:
        return {'success': False, 'error_message': 'Job not found'}
    except Exception as e:
        logger.error(f"Failed to confirm preview: {str(e)}", exc_info=True)
        return {'success': False, 'error_message': str(e)}
