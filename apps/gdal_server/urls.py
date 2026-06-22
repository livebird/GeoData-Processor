from django.urls import path
from . import views

urlpatterns = [
    path('', views.root, name='root'),
    path('app-info', views.app_info, name='app-info'),
    path('health', views.health, name='health'),
    path('supported-conversions', views.supported_conversions, name='supported-conversions'),
    path('convert', views.convert, name='convert'),
    path('task/<str:task_id>', views.task_detail, name='task-detail'),
    path('status/<str:task_id>', views.status, name='status'),
    path('download/<str:task_id>', views.download, name='download'),
]
