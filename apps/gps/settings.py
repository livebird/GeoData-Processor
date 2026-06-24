import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-geodata-processor-key-for-local-development-only'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_spectacular',
    'converter',
    'converter.audit',
    'converter.dispatch',
    'converter.files',
    'converter.workflows',
    'django_celery_results',
    'django_celery_beat',
    'gdal_server',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gps.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'converter.context_processors.viewer_mode' if os.path.exists(os.path.join(BASE_DIR, 'converter', 'context_processors.py')) else 'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'gps.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'batchconverterkavan',
        'USER': 'postgres',
        'PASSWORD': 'admin123',
        'HOST': 'localhost',      # same server par project ho to localhost
        'PORT': '5432',
    }
}
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# CRS / GDAL policy (SRS §7.6)
GDAL_AXIS_ORDER = os.environ.get('GDAL_AXIS_ORDER', 'TRADITIONAL_GIS_ORDER')
os.environ.setdefault('OSR_DEFAULT_AXIS_MAPPING_STRATEGY', GDAL_AXIS_ORDER)
os.environ.setdefault('OGR_CT_FORCE_TRADITIONAL_GIS_ORDER', 'YES')

GDAL_NTV2_GRID_DIRS = [
    path
    for path in os.environ.get(
        'GDAL_NTV2_GRID_DIRS',
        os.path.join(BASE_DIR, 'proj_grids')
    ).split(os.pathsep)
    if path
]
_proj_search_paths = []
for _key in ('PROJ_DATA', 'PROJ_LIB'):
    if os.environ.get(_key):
        _proj_search_paths.extend(os.environ[_key].split(os.pathsep))
_proj_search_paths.extend(path for path in GDAL_NTV2_GRID_DIRS if os.path.isdir(path))
if _proj_search_paths:
    _proj_search_path = os.pathsep.join(dict.fromkeys(_proj_search_paths))
    os.environ.setdefault('PROJ_DATA', _proj_search_path)
    os.environ.setdefault('PROJ_LIB', _proj_search_path)

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'GeoData Processor API',
    'DESCRIPTION': 'GDAL Processing Server API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

GDAL_SERVER_URL = 'http://127.0.0.1:8002'
MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB
AV_SCAN_ENABLED = False
UPLOAD_DAILY_QUOTA = 5 * 1024 * 1024 * 1024  # 5 GB

# Celery Configuration with RabbitMQ
CELERY_BROKER_URL = 'amqp://guest:guest@localhost:5672//'
CELERY_RESULT_BACKEND = 'rpc://'
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True
