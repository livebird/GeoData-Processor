from celery import shared_task
from celery.utils.log import get_task_logger
import time

logger = get_task_logger(__name__)


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
