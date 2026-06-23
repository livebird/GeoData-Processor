import os
import socket
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gps.settings')

app = Celery('gps')

# Load task modules from all registered Django apps.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Django database as broker and result backend (SRS §4)
# Priority queues configuration (FR-JOB-003)
app.conf.update(
    broker_url='django-db',  # Use Django database as broker
    result_backend='django-db',  # PostgreSQL result backend via django-celery-results
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes (FR-JOB-004)
    task_soft_time_limit=25 * 60,  # 25 minutes (FR-JOB-004)
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_max_memory_per_child=500000000,  # 500MB memory limit (FR-JOB-004)
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=100,
    
    # Priority queues (FR-JOB-003)
    task_queues={
        'high': {
            'exchange': 'high',
            'routing_key': 'high',
        },
        'normal': {
            'exchange': 'normal',
            'routing_key': 'normal',
        },
        'low': {
            'exchange': 'low',
            'routing_key': 'low',
        },
    },
    task_default_queue='normal',
    task_default_exchange='normal',
    task_default_routing_key='normal',
    
    # Retry configuration (FR-JOB-006)
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,  # 10 minutes max backoff
    task_retry_jitter=True,
    task_retry_kwargs={'max_retries': 3},
    
    # Beat schedule for periodic tasks (FR-JOB-008, FR-JOB-010)
    beat_schedule={
        'cleanup-orphaned-jobs': {
            'task': 'converter.tasks.cleanup_orphaned_jobs',
            'schedule': crontab(minute='*/30'),  # Run every 30 minutes
        },
    },
)

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
