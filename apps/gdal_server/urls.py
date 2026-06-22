from django.urls import path
from . import views

urlpatterns = [
    # Health and info endpoints
    path('health/', views.health, name='health'),
    path('info/', views.app_info, name='app-info'),
    path('supported-conversions/', views.supported_conversions, name='supported-conversions'),
    
    # Files endpoints (GDAL-specific file operations)
    path('files/upload/', views.file_upload, name='file-upload'),
    path('files/ingest-remote/', views.ingest_remote, name='ingest-remote'),
    path('files/<str:file_id>/', views.file_detail, name='file-detail'),
    path('files/<str:file_id>/metadata/', views.file_metadata, name='file-metadata'),
    path('files/<str:file_id>/validate/', views.file_validate, name='file-validate'),
    path('files/<str:file_id>/validation-result/', views.file_validation_result, name='file-validation-result'),
    
    # Workflows endpoints
    path('workflows/', views.workflows_list, name='workflows-list'),
    path('workflows/<str:code>/run/', views.workflow_run, name='workflow-run'),
    
    # Jobs endpoints
    path('jobs/', views.jobs_list, name='jobs-list'),
    path('jobs/<str:task_id>/', views.task_detail, name='job-detail'),
    path('jobs/<str:task_id>/status/', views.status, name='job-status'),
    path('jobs/<str:task_id>/logs/', views.job_logs, name='job-logs'),
    path('jobs/<str:task_id>/cancel/', views.job_cancel, name='job-cancel'),
    path('jobs/<str:task_id>/retry/', views.job_retry, name='job-retry'),
    path('jobs/<str:task_id>/confirm-preview/', views.job_confirm_preview, name='job-confirm-preview'),
    path('jobs/<str:task_id>/abort-after-preview/', views.job_abort_after_preview, name='job-abort-after-preview'),
    
    # Preview endpoints
    path('jobs/<str:task_id>/preview/summary/', views.preview_summary, name='preview-summary'),
    path('jobs/<str:task_id>/preview/features/', views.preview_features, name='preview-features'),
    path('jobs/<str:task_id>/preview/attributes/', views.preview_attributes, name='preview-attributes'),
    
    # Outputs and dispatched layers
    path('outputs/<str:task_id>/download/', views.download, name='output-download'),
    path('dispatched-layers/', views.dispatched_layers_list, name='dispatched-layers-list'),
    path('dispatched-layers/<str:layer_id>/', views.dispatched_layer_detail, name='dispatched-layer-detail'),
    path('dispatched-layers/<str:layer_id>/redispatch/', views.redispatch_layer, name='redispatch-layer'),
    
    # Destination credentials
    path('destination-credentials/', views.destination_credentials_list, name='destination-credentials-list'),
    path('destination-credentials/create/', views.destination_credentials_create, name='destination-credentials-create'),
    
    # Admin endpoints
    path('admin/stats/', views.admin_stats, name='admin-stats'),
    path('admin/audit/', views.admin_audit, name='admin-audit'),
]
