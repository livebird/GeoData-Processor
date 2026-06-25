from django.urls import path
from . import views

app_name = 'converter'

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('convert', views.convert_files, name='convert_files_no_slash'),
    path('convert/', views.convert_files, name='convert_files'),
    path('convert/status/<uuid:task_id>/', views.conversion_job_status, name='convert_job_status'),
    path('convert/status/<uuid:task_id>', views.conversion_job_status, name='convert_job_status_no_slash'),
    path('gdal_callback/', views.gdal_callback, name='gdal_callback'),
    path('gdal_callback', views.gdal_callback, name='gdal_callback_no_slash'),
    path('location-export/', views.location_export, name='location_export'),
    path('download/<str:folder_id>/', views.download_results, name='download_results'),
    path('search/', views.search, name='search'),
    path('file/', views.file_detail, name='file_detail'),
    path('preview/', views.preview_page, name='preview'),
    path('api/preview/<uuid:task_id>/', views.preview_data, name='preview_data'),
    path('geojson-reader/', views.geojson_reader, name='geojson_reader'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('admin-panel/jobs/create/', views.admin_job_create, name='admin_job_create'),
    path('admin-panel/jobs/<uuid:task_id>/', views.admin_job_detail, name='admin_job_detail'),
    path('admin-panel/jobs/<uuid:task_id>/edit/', views.admin_job_edit, name='admin_job_edit'),
    path('admin-panel/jobs/<uuid:task_id>/delete/', views.admin_job_delete, name='admin_job_delete'),
    path('admin-panel/logs/create/', views.admin_log_create, name='admin_log_create'),
    path('admin-panel/logs/<int:log_id>/', views.admin_log_detail, name='admin_log_detail'),
    path('admin-panel/logs/<int:log_id>/edit/', views.admin_log_edit, name='admin_log_edit'),
    path('admin-panel/logs/<int:log_id>/delete/', views.admin_log_delete, name='admin_log_delete'),
    # Resumable Tus.io upload URLs
    path('api/upload/resumable/', views.tus_upload_init, name='tus_upload_init'),
    path('api/upload/resumable/<uuid:upload_id>/', views.tus_upload_chunk, name='tus_upload_chunk'),
    # Raster Spike URLs (v1.0)
    path('raster-spike/', views.raster_spike, name='raster_spike'),
    path('api/raster/metadata/', views.extract_raster_metadata, name='extract_metadata'),
    path('api/raster/reproject/', views.reproject_raster_file, name='reproject_raster'),
    path('api/raster/cog/', views.convert_to_cog_file, name='convert_cog'),
    path('api/raster/formats/', views.raster_formats_info, name='raster_formats_info'),
    path('database/', views.database_viewer, name='database_viewer'),
    path('toggle-viewer-mode/', views.toggle_viewer_mode, name='toggle_viewer_mode'),

    # Operator UI URLs
    path('files/upload/', views.file_upload_page, name='file_upload_page'),
    path('files/', views.file_list, name='file_list'),
    path('files/<uuid:file_id>/', views.operator_file_detail, name='operator_file_detail'),
    path('files/<uuid:file_id>/validation/', views.file_validation_result, name='file_validation_result'),
    path('files/<uuid:file_id>/assign-crs/', views.assign_crs, name='assign_crs'),

    path('workflows/', views.workflow_catalog, name='workflow_catalog'),
    path('workflows/<slug:code>/run/', views.workflow_run, name='workflow_run'),

    path('jobs/', views.job_list, name='job_list'),
    path('jobs/<uuid:job_id>/', views.operator_job_detail, name='operator_job_detail'),
    path('jobs/<uuid:job_id>/logs/', views.job_logs_view, name='job_logs_view'),
    path('jobs/<uuid:job_id>/preview/', views.job_preview_page, name='job_preview_page'),

    path('outputs/', views.output_list, name='output_list'),
    path('outputs/<uuid:job_id>/download/', views.output_download, name='output_download'),

    path('dispatched-layers/', views.dispatched_layers_list, name='dispatched_layers_list'),
    path('dispatched-layers/<uuid:layer_id>/', views.dispatched_layer_detail, name='dispatched_layer_detail'),
    path('dispatched-layers/<uuid:layer_id>/redispatch/', views.redispatch_action, name='redispatch_action'),

    # API v1 endpoints
    path('api/v1/files/upload/tus', views.api_tus_upload, name='api_tus_upload'),
    path('api/v1/outputs/<uuid:job_id>/download', views.api_output_download, name='api_output_download'),
    path('api/v1/jobs/<uuid:job_id>/preview/summary', views.api_job_preview_summary, name='api_job_preview_summary'),
    path('api/v1/jobs/<uuid:job_id>/preview/features', views.api_job_preview_features, name='api_job_preview_features'),
    path('api/v1/jobs/<uuid:job_id>/preview/attributes', views.api_job_preview_attributes, name='api_job_preview_attributes'),
    path('api/v1/jobs/<uuid:job_id>/confirm-preview', views.api_job_confirm_preview, name='api_job_confirm_preview'),
    path('api/v1/jobs/<uuid:job_id>/abort-after-preview', views.api_job_abort_after_preview, name='api_job_abort_after_preview'),

    # Transform Tools
    path('transform/', views.transform_page, name='transform_page'),
    path('transform/api/', views.transform_api, name='transform_api'),
]
