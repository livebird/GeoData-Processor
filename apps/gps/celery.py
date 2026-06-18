import os
from celery import Celery
import time

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gps.settings')

app = Celery('gps')

# Load task modules from all registered Django apps.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Auto-execute tasks on startup to populate Flower tables
@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Execute tasks automatically after a short delay to populate Flower tables
    from converter.tasks import (
        process_file_conversion,
        send_email_notification,
        generate_report,
        cleanup_old_files,
        workflow_dispatch_download,
        workflow_dispatch_feature_mapper,
        workflow_dispatch_external_webhook,
        workflow_dispatch_external_database
    )
    
    # Execute basic tasks
    sender.add_periodic_task(5.0, debug_task.s(), name='Auto debug task')
    sender.add_periodic_task(10.0, process_file_conversion.s('example.pdf', 'docx'), name='Auto file conversion')
    sender.add_periodic_task(15.0, send_email_notification.s('user@example.com', 'Auto notification'), name='Auto email notification')
    sender.add_periodic_task(20.0, generate_report.s('monthly_sales'), name='Auto report generation')
    sender.add_periodic_task(25.0, cleanup_old_files.s(days=50), name='Auto cleanup')
    
    # Execute workflow tasks
    sender.add_periodic_task(30.0, workflow_dispatch_download.s('data.geojson', 'geojson'), name='Auto workflow download')
    sender.add_periodic_task(35.0, workflow_dispatch_feature_mapper.s('data.geojson', 'https://feature-mapper.example.com/webhook', 'secret_key'), name='Auto workflow feature mapper')
    sender.add_periodic_task(40.0, workflow_dispatch_external_webhook.s('data.geojson', 'https://customer.example.com/api/webhook', {}), name='Auto workflow external webhook')
    sender.add_periodic_task(45.0, workflow_dispatch_external_database.s('data.geojson', 'postgresql://user:password@localhost:5432/gis_db', 'features'), name='Auto workflow external database')

# RabbitMQ as broker and backend
app.conf.update(
    broker_url='amqp://guest:guest@localhost:5672//',
    result_backend='rpc://',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=100,
)

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
