import os
import json
import uuid
import shutil
import zipfile
import datetime
import re
import threading
import traceback
from django.db import connections, models
import hashlib
import tempfile
import requests
from requests.adapters import HTTPAdapter
import urllib.parse
from urllib3.util import Retry
from .models import UploadQuotaLog, GeoFile
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse, JsonResponse, FileResponse
from django.conf import settings
from .batchconvert import (
    batch_convert,
    RASTER_FORMATS,
    get_gdal_info,
    _read_csv_as_geodataframe,
    csv_has_spatial_columns,
    path_matches_driver_ext,
)
from .raster_spike import get_raster_metadata, reproject_raster, convert_to_cog, batch_reproject_rasters, batch_convert_to_cog, RasterMetadata
from django.utils import timezone
from .models import ConversionInputFile, ConversionJob, SearchLog, LocationExport
from django.db.models import Q
from django import forms
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from .gdal_client import get_status as get_gdal_server_status
from .gdal_client import submit_conversion as submit_gdal_conversion
from .operator_sync import (
    ensure_default_workflows,
    record_location_export_dispatch,
    sync_conversion_job_completed,
    sync_conversion_job_failed,
    sync_conversion_job_started,
)

# ────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS & UPLOAD VALIDATION
# ────────────────────────────────────────────────────────────────

MAX_UPLOAD_SIZE = getattr(settings, 'MAX_UPLOAD_SIZE', 5 * 1024 * 1024 * 1024) # 5 GB
AV_SCAN_ENABLED = getattr(settings, 'AV_SCAN_ENABLED', False)

ALLOWED_EXTENSIONS = {
    '.shp', '.shx', '.dbf', '.prj', '.cpg', '.geojson', '.json', '.kml', '.gpkg',
    '.gdb', '.dxf', '.csv', '.tif', '.tiff', '.png', '.jpg', '.jpeg',
    '.pdf', '.fgb', '.parquet', '.arrow', '.avro', '.gml', '.xsd', '.zip'
}

def csrf_failure(request, reason=""):
    """Return JSON for fetch/API CSRF failures instead of Django's HTML 403 page."""
    accept = request.META.get("HTTP_ACCEPT", "")
    requested_with = request.META.get("HTTP_X_REQUESTED_WITH", "")
    json_paths = ("/convert", "/api/", "/location-export", "/gdal_callback")
    wants_json = (
        "application/json" in accept
        or requested_with == "XMLHttpRequest"
        or any(request.path.startswith(path) for path in json_paths)
    )
    if wants_json:
        return JsonResponse(
            {
                "error": "Security check failed. Refresh the page and try again.",
                "detail": reason,
            },
            status=403,
        )
    return HttpResponse("Forbidden: CSRF verification failed.", status=403)

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def check_path_traversal(filename):
    if not filename:
        return False
    normalized = os.path.normpath(filename)
    if normalized.startswith('..') or '..' in normalized or '/' in filename or '\\' in filename:
        return True
    return False

def scan_file_for_malware(file_path):
    if not AV_SCAN_ENABLED:
        return True
    hook = getattr(settings, 'AV_SCAN_HOOK', None)
    if hook and callable(hook):
        try:
            return hook(file_path)
        except Exception as e:
            print(f"[ERROR] AV scan hook failed: {e}")
            return False
    if "eicar" in os.path.basename(file_path).lower():
        return False
    return True

def validate_file_ext_and_mime(file_path, original_name):
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}")
    
    try:
        with open(file_path, 'rb') as f:
            header = f.read(2048)
    except Exception as e:
        raise ValueError(f"Cannot read file header: {str(e)}")
        
    if ext == '.zip':
        if not header.startswith(b'PK\x03\x04'):
            raise ValueError("Invalid ZIP file signature.")
    elif ext == '.pdf':
        if not header.startswith(b'%PDF-'):
            raise ValueError("Invalid PDF file signature.")
    elif ext == '.png':
        if not header.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError("Invalid PNG file signature.")
    elif ext in ('.jpg', '.jpeg'):
        if not header.startswith(b'\xff\xd8\xff'):
            raise ValueError("Invalid JPEG file signature.")
    elif ext in ('.tif', '.tiff'):
        if not (header.startswith(b'II*\x00') or header.startswith(b'MM\x00*')):
            raise ValueError("Invalid TIFF file signature.")
    elif ext in ('.gpkg', '.sqlite'):
        if not header.startswith(b'SQLite format 3\x00'):
            raise ValueError("Invalid GeoPackage/SQLite file signature.")
    elif ext in ('.geojson', '.json'):
        stripped = header.strip()
        if not (stripped.startswith(b'{') or stripped.startswith(b'[')):
            raise ValueError("Invalid GeoJSON file signature (must start with { or [).")
    elif ext in ('.kml', '.gml', '.xsd'):
        stripped = header.strip()
        if not (b'<' in stripped):
            raise ValueError("Invalid XML/KML/GML/XSD file signature.")

def validate_shapefile_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as z:
        names = z.namelist()
        
    # Check if there are any .shp files. If so, it's a shapefile ZIP
    shp_files = [n for n in names if n.lower().endswith('.shp')]
    prj_missing = False
    for shp in shp_files:
        base = shp[:-4]
        shx = base + '.shx'
        dbf = base + '.dbf'
        prj = base + '.prj'
        
        shx_exists = any(n.lower() == shx.lower() for n in names)
        dbf_exists = any(n.lower() == dbf.lower() for n in names)
        if not shx_exists or not dbf_exists:
            raise ValueError(f"Shapefile ZIP is missing required components. For '{shp}', must include both '{base}.shx' and '{base}.dbf'.")
        
        prj_exists = any(n.lower() == prj.lower() for n in names)
        if not prj_exists:
            prj_missing = True
            
    return prj_missing

def check_and_log_quota(user, ip_address, size_bytes):
    quota_limit = getattr(settings, 'UPLOAD_DAILY_QUOTA', 5 * 1024 * 1024 * 1024) # 5 GB
    since = timezone.now() - datetime.timedelta(days=1)
    
    if user and user.is_authenticated:
        used = UploadQuotaLog.objects.filter(user=user, uploaded_at__gte=since).aggregate(total=models.Sum('size_bytes'))['total'] or 0
    else:
        used = UploadQuotaLog.objects.filter(ip_address=ip_address, uploaded_at__gte=since).aggregate(total=models.Sum('size_bytes'))['total'] or 0
        
    if used + size_bytes > quota_limit:
        raise ValueError(f"Upload quota exceeded. You have already uploaded {format_bytes(used)} in the last 24 hours (limit: {format_bytes(quota_limit)}).")
        
    UploadQuotaLog.objects.create(
        user=user if user and user.is_authenticated else None,
        ip_address=ip_address,
        size_bytes=size_bytes
    )

def validate_remote_url(remote_url):
    parsed = urllib.parse.urlparse(remote_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Remote URL must start with http:// or https://. To convert a local file, use the local upload tab.")


def is_local_input_path(value):
    if not value:
        return False
    if os.path.isabs(value) or re.match(r"^[a-zA-Z]:[\\/]", value) or value.startswith("\\\\"):
        return True
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme == "file":
        return True
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return False
    return False


def normalize_local_input_path(value):
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme == "file":
        return urllib.parse.unquote(parsed.path.lstrip("/")) if os.name == "nt" else urllib.parse.unquote(parsed.path)
    return value


def local_path_size(path, max_size):
    if os.path.isfile(path):
        return os.path.getsize(path), 1

    total = 0
    file_count = 0
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            file_path = os.path.join(root, filename)
            total += os.path.getsize(file_path)
            file_count += 1
            if total > max_size:
                raise ValueError(f"Local input exceeds maximum limit of {format_bytes(max_size)}.")
    return total, file_count


def copy_local_input_path(source_path, input_dir, max_size):
    source_path = normalize_local_input_path(source_path)
    if not os.path.exists(source_path):
        raise ValueError(f"Local path does not exist: {source_path}")

    total_size, file_count = local_path_size(source_path, max_size)
    base_name = os.path.basename(os.path.normpath(source_path)) or "local_input"
    if check_path_traversal(base_name):
        raise ValueError("Path traversal attempt detected in local path.")

    if os.path.isfile(source_path):
        destination = os.path.join(input_dir, base_name)
        shutil.copy2(source_path, destination)
        return [destination], total_size, 1

    destination = os.path.join(input_dir, base_name)
    shutil.copytree(source_path, destination)
    copied_paths = []
    for root, dirs, filenames in os.walk(destination):
        copied_paths.extend(os.path.join(root, d) for d in dirs)
        copied_paths.extend(os.path.join(root, f) for f in filenames)
    return copied_paths, total_size, file_count


def make_upload_workspace():
    upload_root = os.path.join(settings.MEDIA_ROOT, 'uploads')
    os.makedirs(upload_root, exist_ok=True)
    workspace = os.path.join(upload_root, str(uuid.uuid4()))
    os.makedirs(workspace)
    return workspace


def _file_sha256(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as source:
        for chunk in iter(lambda: source.read(65536), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_job_output_archive(job):
    """Create and attach a downloadable ZIP output for operator workflow jobs."""
    if job.output_file and job.output_file.storage_path and os.path.isfile(job.output_file.storage_path):
        return job.output_file

    if not job.input_file or not job.input_file.storage_path or not os.path.exists(job.input_file.storage_path):
        raise FileNotFoundError("Input file is missing, so no output archive can be generated.")

    output_dir = os.path.join(settings.MEDIA_ROOT, 'outputs', str(job.id))
    os.makedirs(output_dir, exist_ok=True)
    output_name = f"{job.workflow_code or 'workflow'}_{str(job.id)[:8]}_output.zip"
    output_path = os.path.join(output_dir, output_name)
    input_path = job.input_file.storage_path

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if os.path.isdir(input_path):
            for root, _, filenames in os.walk(input_path):
                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    arcname = os.path.relpath(file_path, input_path).replace("\\", "/")
                    zipf.write(file_path, arcname)
        else:
            zipf.write(input_path, os.path.basename(input_path))

    output_file = GeoFile.objects.create(
        original_file_name=output_name,
        source_type='local',
        file_type='.zip',
        mime_type='application/zip',
        storage_backend='local',
        storage_path=output_path,
        size_bytes=os.path.getsize(output_path),
        checksum_sha256=_file_sha256(output_path),
        uploaded_by=job.requested_by,
    )
    job.output_file = output_file
    job.save(update_fields=['output_file', 'updated_at'])
    return output_file


def ingest_remote_url(remote_url, auth_headers_str=None, expected_checksum=None, max_size=5*1024*1024*1024):
    validate_remote_url(remote_url)

    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) GeoProcessingServer/1.0'}
    if auth_headers_str:
        try:
            custom_headers = json.loads(auth_headers_str)
            if isinstance(custom_headers, dict):
                headers.update(custom_headers)
        except Exception as e:
            raise ValueError(f"Invalid auth headers format: {str(e)}")

    try:
        head_resp = session.head(remote_url, headers=headers, timeout=15, allow_redirects=True)
        if head_resp.ok:
            cl = head_resp.headers.get('Content-Length')
            if cl and int(cl) > max_size:
                raise ValueError(f"Remote file exceeds maximum limit of {format_bytes(max_size)}.")
    except Exception:
        pass

    resp = session.get(remote_url, headers=headers, timeout=30, stream=True, allow_redirects=True)
    resp.raise_for_status()

    cl = resp.headers.get('Content-Length')
    if cl and int(cl) > max_size:
        raise ValueError(f"Remote file exceeds maximum limit of {format_bytes(max_size)}.")

    sha256 = hashlib.sha256()
    temp_fd, temp_path = tempfile.mkstemp()
    size = 0
    try:
        with os.fdopen(temp_fd, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    size += len(chunk)
                    if size > max_size:
                        raise ValueError(f"Remote file exceeds maximum limit of {format_bytes(max_size)}.")
                    f.write(chunk)
                    sha256.update(chunk)
    except Exception:
        os.remove(temp_path)
        raise

    checksum = sha256.hexdigest()
    if expected_checksum and expected_checksum.strip().lower() != checksum.lower():
        os.remove(temp_path)
        raise ValueError(f"Checksum mismatch: expected {expected_checksum}, calculated {checksum}")

    return temp_path, checksum, size


# ────────────────────────────────────────────────────────────────
# TUS.IO RESUMABLE UPLOAD VIEWS
# ────────────────────────────────────────────────────────────────

from django.views.decorators.csrf import csrf_exempt

TUS_UPLOAD_DIR = os.path.join(settings.MEDIA_ROOT, 'tus_uploads')

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def tus_upload_init(request):
    os.makedirs(TUS_UPLOAD_DIR, exist_ok=True)
    
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        response["Tus-Resumable"] = "1.0.0"
        response["Tus-Version"] = "1.0.0"
        response["Tus-Max-Size"] = str(MAX_UPLOAD_SIZE)
        response["Tus-Extension"] = "creation,termination"
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, GET, HEAD, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Tus-Resumable, Upload-Length, Upload-Metadata, Upload-Offset, Content-Type"
        return response

    tus_version = request.headers.get("Tus-Resumable")
    if tus_version != "1.0.0":
        return HttpResponse("Unsupported Tus version", status=412)

    upload_length_str = request.headers.get("Upload-Length")
    if not upload_length_str:
        return HttpResponse("Missing Upload-Length header", status=400)
    
    try:
        upload_length = int(upload_length_str)
    except ValueError:
        return HttpResponse("Invalid Upload-Length", status=400)

    if upload_length > MAX_UPLOAD_SIZE:
        return HttpResponse(f"File size exceeds limit of {format_bytes(MAX_UPLOAD_SIZE)}", status=413)

    # Quota check
    try:
        check_and_log_quota(request.user, request.META.get("REMOTE_ADDR"), upload_length)
    except ValueError as quota_err:
        return HttpResponse(str(quota_err), status=429)

    metadata_str = request.headers.get("Upload-Metadata", "")
    metadata = {}
    if metadata_str:
        import base64
        for pair in metadata_str.split(","):
            parts = pair.strip().split(" ")
            if len(parts) == 2:
                key = parts[0]
                try:
                    val = base64.b64decode(parts[1]).decode("utf-8")
                    metadata[key] = val
                except Exception:
                    pass

    filename = metadata.get("filename", "uploaded_file.bin")
    
    if check_path_traversal(filename):
        return JsonResponse({"error": "Path traversal attempt detected in filename"}, status=400)

    upload_id = str(uuid.uuid4())
    file_path = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.bin")
    meta_path = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.json")

    with open(file_path, "wb") as f:
        pass

    with open(meta_path, "w") as f:
        json.dump({
            "id": upload_id,
            "filename": filename,
            "length": upload_length,
            "offset": 0,
            "metadata": metadata,
            "created_at": timezone.now().isoformat(),
        }, f)

    location = f"/api/upload/resumable/{upload_id}/"
    response = HttpResponse(status=201)
    response["Location"] = location
    response["Tus-Resumable"] = "1.0.0"
    response["Access-Control-Expose-Headers"] = "Location, Tus-Resumable"
    response["Access-Control-Allow-Origin"] = "*"
    return response

@csrf_exempt
@require_http_methods(["HEAD", "PATCH", "DELETE", "OPTIONS"])
def tus_upload_chunk(request, upload_id):
    os.makedirs(TUS_UPLOAD_DIR, exist_ok=True)
    upload_id_str = str(upload_id)
    file_path = os.path.join(TUS_UPLOAD_DIR, f"{upload_id_str}.bin")
    meta_path = os.path.join(TUS_UPLOAD_DIR, f"{upload_id_str}.json")

    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        response["Tus-Resumable"] = "1.0.0"
        response["Tus-Version"] = "1.0.0"
        response["Tus-Max-Size"] = str(MAX_UPLOAD_SIZE)
        response["Tus-Extension"] = "creation,termination"
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, GET, HEAD, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Tus-Resumable, Upload-Length, Upload-Metadata, Upload-Offset, Content-Type"
        return response

    if not os.path.exists(file_path) or not os.path.exists(meta_path):
        return HttpResponse("Upload not found", status=404)

    with open(meta_path, "r") as f:
        meta = json.load(f)

    if request.method == "HEAD":
        response = HttpResponse(status=200)
        response["Upload-Offset"] = str(meta["offset"])
        response["Upload-Length"] = str(meta["length"])
        response["Tus-Resumable"] = "1.0.0"
        response["Cache-Control"] = "no-store"
        response["Access-Control-Expose-Headers"] = "Upload-Offset, Upload-Length, Tus-Resumable"
        response["Access-Control-Allow-Origin"] = "*"
        return response

    elif request.method == "DELETE":
        try:
            os.remove(file_path)
            os.remove(meta_path)
        except Exception:
            pass
        response = HttpResponse(status=204)
        response["Tus-Resumable"] = "1.0.0"
        response["Access-Control-Allow-Origin"] = "*"
        return response

    elif request.method == "PATCH":
        tus_version = request.headers.get("Tus-Resumable")
        if tus_version != "1.0.0":
            return HttpResponse("Unsupported Tus version", status=412)

        content_type = request.headers.get("Content-Type")
        if content_type != "application/offset+octet-stream":
            return HttpResponse("Invalid Content-Type", status=400)

        offset_str = request.headers.get("Upload-Offset")
        if not offset_str:
            return HttpResponse("Missing Upload-Offset", status=400)
        try:
            offset = int(offset_str)
        except ValueError:
            return HttpResponse("Invalid Upload-Offset", status=400)

        if offset != meta["offset"]:
            return HttpResponse("Offset mismatch", status=409)

        # Write chunk in streamed fashion
        with open(file_path, "ab") as f:
            while True:
                chunk = request.read(65536)
                if not chunk:
                    break
                f.write(chunk)

        meta["offset"] = os.path.getsize(file_path)

        with open(meta_path, "w") as f:
            json.dump(meta, f)

        # If completed, we do extension & malware check
        if meta["offset"] >= meta["length"]:
            try:
                validate_file_ext_and_mime(file_path, meta["filename"])
                if not scan_file_for_malware(file_path):
                    raise ValueError("File contains potential malware signature.")
            except Exception as e:
                # Cleanup on invalid file
                try:
                    os.remove(file_path)
                    os.remove(meta_path)
                except Exception:
                    pass
                return HttpResponse(str(e), status=400)

        response = HttpResponse(status=204)
        response["Upload-Offset"] = str(meta["offset"])
        response["Tus-Resumable"] = "1.0.0"
        response["Access-Control-Expose-Headers"] = "Upload-Offset, Tus-Resumable"
        response["Access-Control-Allow-Origin"] = "*"
        return response


# ────────────────────────────────────────────────────────────────
# AUTHENTICATION FORMS & VIEWS
# ────────────────────────────────────────────────────────────────

class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput())

class SignUpForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    password1 = forms.CharField(widget=forms.PasswordInput())
    password2 = forms.CharField(widget=forms.PasswordInput())
    agree_terms = forms.BooleanField(required=True)

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('Passwords do not match.')
        if password1 and len(password1) < 8:
            raise forms.ValidationError('Password must be at least 8 characters long.')
        return cleaned_data

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('converter:index')
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is None:
                try:
                    user_obj = User.objects.get(email=username)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass
            if user is not None:
                login(request, user)
                return redirect('converter:index')
            else:
                form.add_error(None, 'Invalid username/email or password.')
    else:
        form = LoginForm()
    return render(request, 'converter/login.html', {'form': form})

@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('converter:index')
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password1'],
                    first_name=form.cleaned_data['first_name'],
                    last_name=form.cleaned_data['last_name']
                )
                login(request, user)
                return redirect('converter:index')
            except IntegrityError:
                form.add_error(None, 'An error occurred during registration. Please try again.')
    else:
        form = SignUpForm()
    return render(request, 'converter/signup.html', {'form': form})

@require_http_methods(["GET"])
def logout_view(request):
    logout(request)
    return redirect('converter:index')

# Supported drivers mapping
SUPPORTED_DRIVERS = {
    'ESRI Shapefile': '.shp',
    'GeoJSON': '.geojson',
    'KML': '.kml',
    'GeoPackage': '.gpkg',
    'OpenFileGDB': '.gdb',
    'DXF': '.dxf',
    'CSV': '.csv',
    'GTiff': '.tif',
    'GeoTIFF': '.tif',
    'PNG': '.png',
    'JPEG': '.jpg',
    'FlatGeobuf': '.fgb',
    'GeoParquet': '.parquet',
    'Arrow IPC': '.arrow',
    'Avro': '.avro',
    'GML': '.gml'
}

# Mapping of drivers that might be directories
DIRECTORY_DRIVERS = ['OpenFileGDB', 'ESRI Shapefile'] 

VECTOR_OUTPUT_EXTENSIONS = {
    'ESRI Shapefile': '.shp',
    'GeoJSON': '.geojson',
    'KML': '.kml',
    'GPKG': '.gpkg',
    'OpenFileGDB': '.gdb',
    'DXF': '.dxf',
    'CSV': '.csv',
    'FlatGeobuf': '.fgb',
    'GeoParquet': '.parquet',
    'Arrow IPC': '.arrow',
    'Avro': '.avro',
    'GML': '.gml'
}

RASTER_OUTPUT_EXTENSIONS = {
    'GTiff': '.tif',
    'GeoTIFF': '.tif',
    'PNG': '.png',
    'JPEG': '.jpg',
    
}

FORMAT_ALIASES = {
    'GeoTIFF': 'GTiff',
    'SHP': 'ESRI Shapefile',
    'GPKG': 'GeoPackage',
    'CSV (with coordinates)': 'CSV',
    'CSV (w/ coords)': 'CSV',
    'opnfilegdb': 'OpenFileGDB',
    'arrowipc': 'Arrow IPC',
}

VECTOR_TO_VECTOR = {
    'ESRI Shapefile': {
        'GeoJSON', 'GeoPackage', 'KML', 'GML', 'CSV', 'DXF',
        'FlatGeobuf', 'GeoParquet', 'Avro', 'Arrow IPC', 'OpenFileGDB',
    },
    'GeoJSON': {
        'ESRI Shapefile', 'GeoPackage', 'KML', 'CSV', 'DXF',
        'FlatGeobuf', 'GeoParquet', 'GML',
    },
    'GeoPackage': {
        'ESRI Shapefile', 'GeoJSON', 'KML', 'DXF', 'CSV',
        'FlatGeobuf', 'GeoParquet', 'GML', 'OpenFileGDB',
    },
    'KML': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage', 'CSV', 'DXF'},
    'OpenFileGDB': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage', 'CSV', 'FlatGeobuf'},
    'DXF': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage'},
    'CSV': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage', 'KML'},
    'FlatGeobuf': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage', 'GeoParquet'},
    'GeoParquet': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage', 'FlatGeobuf'},
    'GML': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage'},
    'Avro': {'GeoJSON', 'GeoPackage', 'FlatGeobuf'},
    'Arrow IPC': {'GeoJSON', 'GeoParquet', 'GeoPackage'},
}

RASTER_TO_RASTER = {
    'GeoTIFF': {'PNG', 'JPEG'},
    'GTiff': {'PNG', 'JPEG'},
    'PNG': {'JPEG', 'GeoTIFF', 'GTiff'},
    'JPEG': {'PNG', 'GeoTIFF', 'GTiff'},
}

VECTOR_TO_RASTER = {
    'ESRI Shapefile': {'PNG', 'JPEG', 'GeoTIFF', 'GTiff'},
    'GeoJSON': {'PNG', 'JPEG', 'GeoTIFF', 'GTiff'},
    'GeoPackage': {'PNG', 'JPEG', 'GeoTIFF', 'GTiff'},
    'KML': {'PNG', 'JPEG'},
    'DXF': {'PNG', 'JPEG'},
}

RASTER_TO_VECTOR = {
    'PNG': {'ESRI Shapefile', 'GeoJSON', 'GeoPackage'},
    'JPEG': {'ESRI Shapefile', 'GeoJSON'},
    'GeoTIFF': {'ESRI Shapefile', 'GeoJSON'},
    'GTiff': {'ESRI Shapefile', 'GeoJSON'},
}


def _canonical_format_name(name):
    if not name:
        return name
    # Direct match
    if name in FORMAT_ALIASES:
        return FORMAT_ALIASES.get(name)
    # Case-insensitive alias match
    lname = name.lower()
    for k, v in FORMAT_ALIASES.items():
        if k.lower() == lname:
            return v
    # Match against known format keys (case-insensitive)
    known_list = list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()) + list(RASTER_OUTPUT_EXTENSIONS.keys())
    if 'DRIVER_EXTENSIONS' in globals():
        known_list += list(DRIVER_EXTENSIONS.keys())
    known = set(known_list)
    for k in known:
        if k.lower() == lname:
            return k
    # Fallback to title-case for common simple names
    return name


def _parse_requested_formats(raw: str) -> list:
    """Parse a user-provided output-format string tolerant of typos and missing commas.

    Returns a list of canonical format names (may include elements not in known set).
    Uses exact/case-insensitive matching first, then difflib close matches.
    """
    if not raw:
        return []
    import difflib

    # Known names lowercased -> canonical
    known_list = list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()) + list(RASTER_OUTPUT_EXTENSIONS.keys())
    if 'DRIVER_EXTENSIONS' in globals():
        known_list += list(DRIVER_EXTENSIONS.keys())
    known = set(known_list)
    canon_map = {k.lower(): k for k in known}

    parts = [p.strip() for p in str(raw).split(',') if p and p.strip()]
    results: list = []
    for p in parts:
        if not p:
            continue
        # direct canonical match
        c = _canonical_format_name(p)
        if c in known:
            results.append(c)
            continue
        key = p.lower().strip()
        # try exact known token match
        if key in canon_map:
            results.append(canon_map[key]); continue
        # try difflib close matches against known names
        close = difflib.get_close_matches(key, list(canon_map.keys()), n=1, cutoff=0.66)
        if close:
            results.append(canon_map[close[0]])
            continue
        # fallback: try to find any known name that is substring of the cleaned token
        cleaned = re.sub(r'[^a-z0-9]', '', key)
        found = False
        for k_lower, k_canon in canon_map.items():
            if k_lower.replace(' ', '').replace('-', '') in cleaned:
                results.append(k_canon)
                found = True
                break
        if found:
            continue
        # last resort: keep original (so validator reports it invalid)
        results.append(p)
    return results


def _normalize_format_name(name):
    if not name:
        return name
    # Strip and normalize common input names (case-insensitive)
    if isinstance(name, str):
        name = name.strip()
    return _canonical_format_name(name)


def _default_output_format_for_input(input_format):
    input_format = _canonical_format_name(input_format)
    if input_format in {'GTiff', 'GeoTIFF'}:
        return 'PNG'
    if input_format in {'PNG', 'JPEG'}:
        return 'GeoTIFF'
    if input_format == 'GeoJSON':
        return 'GeoPackage'
    if input_format in VECTOR_TO_VECTOR:
        return 'GeoJSON'
    if input_format in RASTER_TO_RASTER:
        return 'PNG'
    return None


def _get_supported_outputs(input_format):
    input_format = _canonical_format_name(input_format)
    if input_format in VECTOR_TO_VECTOR:
        return sorted(list(VECTOR_TO_VECTOR[input_format] | VECTOR_TO_RASTER.get(input_format, set())))
    if input_format in RASTER_TO_RASTER:
        return sorted(list(RASTER_TO_RASTER[input_format] | RASTER_TO_VECTOR.get(input_format, set())))
    return []


def _validate_csv_spatial_input(saved_paths):
    """Reject non-spatial CSV uploads before conversion starts."""
    import pandas as pd

    csv_files = [path for path in saved_paths if path.lower().endswith('.csv')]
    if not csv_files:
        return None

    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, nrows=5)
        except Exception as exc:
            return f'Could not read CSV file "{os.path.basename(csv_path)}": {exc}'
        if not csv_has_spatial_columns(df.columns):
            return (
                f'"{os.path.basename(csv_path)}" is not a spatial CSV. '
                'CSV input requires coordinate columns (lat/lon, latitude/longitude, origin_lat/origin_lon), '
                'a WKT geometry column, or a GeoJSON geometry column. '
                'Schema or API documentation tables cannot be converted.'
            )
    return None


def _validate_conversion_pair(input_format, output_format):
    if input_format == 'Auto-detect':
        return {'valid': True, 'allowed_outputs': []}
    # Treat 'all' (case-insensitive) as any supported input format.
    # Be tolerant of inputs like 'all format shapefile,geojson' by tokenizing words.
    if isinstance(input_format, str):
        tokens = re.split(r'\W+', input_format.strip().lower())
    else:
        tokens = []
    if 'all' in tokens:
        all_inputs = set(list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()))
        allowed_set = set()
        for inf in all_inputs:
            allowed_set.update(_get_supported_outputs(inf))
        allowed_outputs = sorted(list(allowed_set))
        # No specific requested output -> allowed
        if not output_format:
            return {'valid': True, 'allowed_outputs': allowed_outputs}
        # Allow comma-separated requested outputs and validate each
        requested_canon = _parse_requested_formats(output_format)
        invalid = [o for o in requested_canon if o not in allowed_set]
        if invalid:
            return {
                'valid': False,
                'reason': f'Conversion from all to {", ".join(invalid)} is not supported.',
                'allowed_outputs': allowed_outputs,
            }
        return {'valid': True, 'allowed_outputs': allowed_outputs}

    input_format = _canonical_format_name(input_format)
    allowed_outputs = _get_supported_outputs(input_format)
    if not allowed_outputs:
        return {
            'valid': False,
            'reason': f'Unsupported input format: {input_format}',
            'allowed_outputs': [],
        }
    # Support comma-separated requested outputs
    if not output_format:
        return {'valid': True, 'allowed_outputs': allowed_outputs}
    requested_canon = _parse_requested_formats(output_format)
    invalid = [o for o in requested_canon if o not in allowed_outputs]
    if invalid:
        return {
            'valid': False,
            'reason': f'Conversion from {input_format} to {", ".join(invalid)} is not supported.',
            'allowed_outputs': allowed_outputs,
        }
    return {
        'valid': True,
        'allowed_outputs': allowed_outputs,
    }

def _driver_for_source(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.tif', '.tiff', '.png', '.jpg', '.jpeg', '.vrt', '.pdf'):
        return 'raster'
    return 'vector'

def _safe_output_name(source_path, suffix, ext):
    stem = os.path.splitext(os.path.basename(source_path.rstrip(os.sep)))[0] or 'location_export'
    return f"{stem}_{suffix}{ext}"


def _read_custom_avro(file_path):
    """Read a custom Avro-like binary used in this project and return a GeoDataFrame."""
    import io
    import json
    import pandas as pd
    import geopandas as gpd
    from shapely.wkt import loads as wkt_loads

    def _decode_avro_long(stream):
        shift = 0
        result = 0
        while True:
            b = stream.read(1)
            if not b:
                raise EOFError()
            b = b[0]
            result |= (b & 0x7f) << shift
            if not (b & 0x80):
                break
            shift += 7
        return (result >> 1) ^ -(result & 1)

    with open(file_path, 'rb') as f:
        magic = f.read(4)
        if magic != b'Obj\x01':
            raise ValueError("Not a valid custom Avro file")

        elem_count = _decode_avro_long(f)
        metadata = {}
        for _ in range(elem_count):
            k_len = _decode_avro_long(f)
            key = f.read(k_len).decode('utf-8')
            v_len = _decode_avro_long(f)
            val = f.read(v_len)
            metadata[key] = val
        _decode_avro_long(f)

        sync = f.read(16)
        count = _decode_avro_long(f)
        records_len = _decode_avro_long(f)
        records_data = f.read(records_len)

        schema_json = metadata.get('avro.schema').decode('utf-8')
        schema = json.loads(schema_json)
        fields = [field['name'] for field in schema['fields']]

        stream = io.BytesIO(records_data)
        rows = []
        try:
            for _ in range(count):
                row = {}
                for field in fields:
                    status = _decode_avro_long(stream)
                    if status == 0:
                        row[field] = None
                    else:
                        length = _decode_avro_long(stream)
                        val = stream.read(length).decode('utf-8')
                        row[field] = val
                rows.append(row)
        except EOFError:
            pass

        df = pd.DataFrame(rows)
        geom_col = None
        for col in df.columns:
            if 'geometry_wkt' in col or 'geometry_geojson' in col:
                geom_col = col
                break

        if geom_col and not df.empty:
            geoms = []
            for val in df[geom_col]:
                if val:
                    try:
                        geoms.append(wkt_loads(val))
                    except Exception:
                        geoms.append(None)
                else:
                    geoms.append(None)
            gdf = gpd.GeoDataFrame(df, geometry=geoms)
            gdf.set_crs("EPSG:4326", inplace=True)
            cols_to_drop = [c for c in df.columns if 'geometry_wkt' in c or 'geometry_geojson' in c]
            gdf.drop(columns=cols_to_drop, inplace=True, errors='ignore')
            return gdf
        else:
            return gpd.GeoDataFrame(df, geometry=None)

def _location_export_vector(source_path, output_path, output_format, geojson_geom):
    import json
    try:
        import geopandas as gpd
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError(f"GeoPandas/Shapely are required for vector location export: {exc}")

    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise RuntimeError("The source vector file has no features.")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # The drawn geometry is in EPSG:4326
    geom = shape(json.loads(geojson_geom))
    geom_gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
    geom_in_source_crs = geom_gdf.to_crs(gdf.crs).iloc[0].geometry
    
    selected = gdf[gdf.geometry.notna() & gdf.geometry.intersects(geom_in_source_crs)]

    if selected.empty:
        raise RuntimeError("No vector features intersect the selected area.")

    if output_format == 'CSV':
        out = selected.copy()
        out['longitude'] = out.geometry.to_crs("EPSG:4326").centroid.x
        out['latitude'] = out.geometry.to_crs("EPSG:4326").centroid.y
        out.to_csv(output_path, index=False)
    else:
        selected.to_file(output_path, driver=output_format)

    return len(selected)

def _location_export_raster(source_path, output_path, output_format, geojson_geom):
    import json
    try:
        import rasterio
        import rasterio.mask
        import geopandas as gpd
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError(f"Rasterio/GeoPandas are required for raster location export: {exc}")

    geom = shape(json.loads(geojson_geom))

    with rasterio.open(source_path) as src:
        if src.crs is None:
            raise RuntimeError("The source raster has no CRS.")

        geom_gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
        geom_in_source_crs = geom_gdf.to_crs(src.crs).iloc[0].geometry
        
        try:
            out_image, out_transform = rasterio.mask.mask(src, [geom_in_source_crs], crop=True)
            out_meta = src.meta.copy()
        except ValueError as e:
            raise RuntimeError(f"Selected area is outside the raster bounds: {e}")
            
        if out_image.size == 0:
            raise RuntimeError("The selected raster window is empty.")

        out_meta.update({
            "driver": output_format,
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform
        })

        if output_format in {'PNG', 'JPEG'}:
            out_meta.update(count=min(out_image.shape[0], 4), dtype='uint8')
            out_image = out_image[:out_meta['count']]
            if out_image.dtype != 'uint8':
                data_min = float(out_image.min())
                data_max = float(out_image.max())
                if data_max > data_min:
                    out_image = ((out_image - data_min) / (data_max - data_min) * 255).astype('uint8')
                else:
                    out_image = out_image.astype('uint8')

        with rasterio.open(output_path, 'w', **out_meta) as dst:
            dst.write(out_image)

    return 1

def index(request):
    """Render the main UI."""
    return render(request, 'converter/index.html', {
        'formats': SUPPORTED_DRIVERS,
        'auto_detect': 'Auto-detect',
        'active_page': 'converter',
    })


def _build_usage_dashboard():
    total_uploads = UploadQuotaLog.objects.count()
    failed_jobs = ConversionJob.objects.filter(status=ConversionJob.STATUS_ERROR).count()
    storage_bytes = GeoFile.objects.aggregate(total=models.Sum('size_bytes'))['total'] or 0

    top_user_rows = list(
        UploadQuotaLog.objects.filter(user__isnull=False)
        .values('user_id')
        .annotate(upload_count=models.Count('id'), total_size=models.Sum('size_bytes'))
        .order_by('-upload_count', '-total_size')[:5]
    )
    users = User.objects.in_bulk([row['user_id'] for row in top_user_rows])
    top_users = []
    for row in top_user_rows:
        user = users.get(row['user_id'])
        top_users.append({
            'label': user.get_username() if user else f"User {row['user_id']}",
            'uploads': row['upload_count'],
            'storage': row['total_size'] or 0,
        })

    return {
        'total_uploads': total_uploads,
        'failed_jobs': failed_jobs,
        'storage_bytes': storage_bytes,
        'storage_display': format_bytes(storage_bytes),
        'top_users': top_users,
    }

def location_export(request):
    """Export data from a source file at a drawn map location."""
    if request.method == 'POST':
        try:
            output_format = request.POST.get('output_format', '').strip()
            geojson_geom = request.POST.get('geojson_geom', '').strip()
            conversion_task_id = request.POST.get('conversion_task_id', '').strip()

            if not geojson_geom:
                return JsonResponse({'error': 'Please choose a place on the map.'}, status=400)

            if not conversion_task_id:
                return JsonResponse({'error': 'Please convert a file first, then use Send Export from the Converter.'}, status=400)

            if not re.fullmatch(r'[0-9a-fA-F-]{36}', conversion_task_id):
                return JsonResponse({'error': 'Invalid converted file reference.'}, status=400)

            task_id = str(uuid.uuid4())
            task_dir = os.path.join(settings.MEDIA_ROOT, task_id)

            # A converted file is already a final ZIP. Location Export now places
            # that ZIP at the chosen map location instead of spatially clipping it.
            conv_zip = os.path.join(settings.MEDIA_ROOT, f"{conversion_task_id}.zip")
            if not os.path.exists(conv_zip):
                return JsonResponse({'error': 'Converted ZIP not found. Please convert the file again.'}, status=400)

            source_file_name = os.path.basename(conv_zip)
            source_kind = 'converted_zip'
            exported_count = 1

            zip_path = os.path.join(settings.MEDIA_ROOT, f"{task_id}.zip")
            shutil.copyfile(conv_zip, zip_path)

            shutil.rmtree(task_dir, ignore_errors=True)

            conversion_job = ConversionJob.objects.filter(task_id=conversion_task_id).first()
            location_export = LocationExport.objects.create(
                task_id=task_id,
                source_file_name=source_file_name,
                source_kind=source_kind,
                output_format=(conversion_job.output_format if conversion_job else output_format),
                geojson_geom=geojson_geom,
                exported_count=exported_count,
                download_url=f'/download/{task_id}/',
                output_zip_relpath=f'{task_id}.zip',
                conversion_job_task_id=conversion_task_id,
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            record_location_export_dispatch(location_export, conversion_job=conversion_job)

            return JsonResponse({
                'success': True,
                'download_url': f'/download/{task_id}/',
                'exported_count': exported_count,
                'source_kind': source_kind,
            })
        except Exception as exc:
            try:
                if 'task_dir' in locals() and os.path.exists(task_dir):
                    shutil.rmtree(task_dir, ignore_errors=True)
            except Exception:
                pass
            return JsonResponse({'error': str(exc)}, status=500)

    return render(request, 'converter/location_export.html', {
        'formats': SUPPORTED_DRIVERS,
        'active_page': 'location_export',
    })


def _conversion_worker(
    *,
    task_id_str,
    task_dir,
    input_dir,
    output_dir,
    input_format,
    input_ext,
    output_format,
    output_ext,
    batch_kwargs,
    gdal_server_url="",
    callback_url="",
):
    """Run GDAL conversion off the request thread so navigation does not cancel work."""
    connections.close_all()
    job = None
    try:
        job = ConversionJob.objects.get(task_id=task_id_str)

        if gdal_server_url:
            try:
                remote_payload = submit_gdal_conversion(
                    gdal_server_url,
                    task_id=task_id_str,
                    input_path=input_dir,
                    input_driver=input_format,
                    input_driver_ext=input_ext,
                    conversion_driver=output_format,
                    conversion_driver_ext=output_ext,
                    callback_url=callback_url,
                    conversion_kwargs=batch_kwargs,
                )
                print(f"[DEBUG] Remote GDAL job submitted: {remote_payload}")
                job.status = ConversionJob.STATUS_STARTED
                job.save(update_fields=["status"])
                return
            except Exception as remote_error:
                print(f"[WARN] Remote GDAL server unavailable; falling back to local conversion: {remote_error}")

        print(f"[DEBUG] About to call batch_convert (background):")
        print(f"  input_path: {input_dir}")
        print(f"  output_path: {output_dir}")
        print(f"  input_driver: {input_format}")
        print(f"  input_ext: {input_ext}")
        print(f"  conversion_driver: {output_format}")
        print(f"  conversion_ext: {output_ext}")

        converted_files = batch_convert(
            input_path=input_dir,
            output_path=output_dir,
            input_driver=input_format,
            input_driver_ext=input_ext,
            conversion_driver=output_format,
            conversion_driver_ext=output_ext,
            **batch_kwargs,
        )

        print(f"[DEBUG] batch_convert returned: {len(converted_files)} files")

        if not converted_files:
            job.status = ConversionJob.STATUS_ERROR
            job.error_message = "No files were produced during conversion."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at"])
            return

        output_files = []
        for root, _, filenames in os.walk(output_dir):
            for filename in filenames:
                output_files.append(os.path.join(root, filename))

        if not output_files:
            job.status = ConversionJob.STATUS_ERROR
            job.error_message = "No output files found in output directory."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at"])
            return

        zip_path = os.path.join(settings.MEDIA_ROOT, f"{task_id_str}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_files:
                arcname = os.path.relpath(file_path, output_dir).replace("\\", "/")
                zipf.write(file_path, arcname)

        quality_score = None
        try:
            for root, _, filenames in os.walk(output_dir):
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in ['.shp', '.geojson', '.gpkg', '.kml', '.parquet', '.fgb', '.csv', '.avro']:
                        target_file = os.path.join(root, filename)
                        import geopandas as gpd
                        import pandas as pd
                        if ext == '.csv':
                            df = pd.read_csv(target_file)
                            try:
                                gdf = _read_csv_as_geodataframe(df)
                            except ValueError:
                                gdf = gpd.GeoDataFrame(df, geometry=None)
                        elif ext == '.parquet':
                            gdf = gpd.read_parquet(target_file)
                        elif ext == '.avro':
                            gdf = _read_custom_avro(target_file)
                        else:
                            gdf = gpd.read_file(target_file)

                        if gdf.crs is None:
                            gdf = gdf.set_crs('EPSG:4326')

                        try:
                            gdf = gdf.to_crs('EPSG:4326')
                        except Exception:
                            pass

                        total = len(gdf) or 0
                        score = 100.0
                        missing_crs = gdf.crs is None
                        if missing_crs:
                            score -= 30.0
                        try:
                            invalid_count = int((~gdf.geometry.is_valid.fillna(False)).sum())
                        except Exception:
                            invalid_count = 0
                        try:
                            dup_count = int(gdf.geometry.duplicated().sum())
                        except Exception:
                            dup_count = 0
                        non_geom_cols = [c for c in gdf.columns if c != 'geometry']
                        empty_attr_count = 0
                        if non_geom_cols:
                            try:
                                attrs = gdf[non_geom_cols]
                                empties = attrs.isnull() | (attrs.applymap(lambda v: isinstance(v, str) and v.strip() == ''))
                                empty_attr_count = int((empties.all(axis=1)).sum())
                            except Exception:
                                empty_attr_count = 0
                        if total:
                            score -= (invalid_count / total) * 40.0
                            score -= (dup_count / total) * 20.0
                            score -= (empty_attr_count / total) * 15.0
                        quality_score = max(0, min(100, int(round(score))))
                        break
                if quality_score is not None:
                    break
        except Exception:
            quality_score = None

        job.status = ConversionJob.STATUS_SUCCESS
        job.output_files_count = len(output_files)
        job.output_zip_relpath = f"{task_id_str}.zip"
        job.download_url = f"/download/{task_id_str}/"
        job.finished_at = timezone.now()
        if quality_score is not None:
            job.quality_score = quality_score
            job.save(
                update_fields=[
                    "status",
                    "output_files_count",
                    "output_zip_relpath",
                    "download_url",
                    "finished_at",
                    "quality_score",
                ]
            )
        else:
            job.save(
                update_fields=[
                    "status",
                    "output_files_count",
                    "output_zip_relpath",
                    "download_url",
                    "finished_at",
                ]
            )

        sync_conversion_job_completed(job, zip_path, output_files_count=len(output_files))
        shutil.rmtree(task_dir)
    except ConversionJob.DoesNotExist:
        print(f"[ERROR] ConversionJob missing for task_id={task_id_str}")
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[ERROR] Conversion process failed: {error_msg}")
        try:
            if job is None:
                job = ConversionJob.objects.get(task_id=task_id_str)
            job.status = ConversionJob.STATUS_ERROR
            job.error_message = str(e)[:4000]
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at"])
            sync_conversion_job_failed(job, str(e))
        except ConversionJob.DoesNotExist:
            pass
        try:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir)
        except Exception:
            pass
    finally:
        connections.close_all()


def _mark_conversion_job_success_from_zip(job, zip_path, relpath):
    """Persist success when the output ZIP exists on disk."""
    job.status = ConversionJob.STATUS_SUCCESS
    job.output_zip_relpath = relpath
    job.download_url = f"/download/{job.task_id}/"
    job.finished_at = timezone.now()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            job.output_files_count = len([n for n in zf.namelist() if not n.endswith("/")])
    except Exception:
        job.output_files_count = job.output_files_count or 1
    job.save(
        update_fields=[
            "status",
            "output_zip_relpath",
            "download_url",
            "finished_at",
            "output_files_count",
        ]
    )
    return job


def _resolve_pending_conversion_job(job):
    """Detect finished conversions when GDAL callback or DB sync did not run."""
    if job.status != ConversionJob.STATUS_STARTED:
        return job

    tid = str(job.task_id)
    zip_path = os.path.join(settings.MEDIA_ROOT, f"{tid}.zip")
    if os.path.exists(zip_path):
        return _mark_conversion_job_success_from_zip(job, zip_path, f"{tid}.zip")

    repo_root = os.path.normpath(os.path.join(str(settings.BASE_DIR), os.pardir))
    fastapi_zip = os.path.normpath(
        os.path.join(repo_root, "gdal_server", "outputs", tid, f"{tid}.zip")
    )
    if os.path.exists(fastapi_zip):
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        try:
            shutil.copy2(fastapi_zip, zip_path)
            return _mark_conversion_job_success_from_zip(job, zip_path, f"{tid}.zip")
        except Exception:
            pass

    gdal_server_url = getattr(settings, "GDAL_SERVER_URL", "").strip()
    if gdal_server_url:
        try:
            remote = get_gdal_server_status(gdal_server_url, tid)
            file_status = remote.get("file_status") or {}
            remote_status = remote.get("status") or file_status.get("status")
            if remote_status == "error":
                job.status = ConversionJob.STATUS_ERROR
                job.error_message = (
                    file_status.get("error") or remote.get("error") or "Conversion failed"
                )[:4000]
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error_message", "finished_at"])
                return job
            if remote_status in ("completed", "success"):
                if not os.path.exists(zip_path) and os.path.exists(fastapi_zip):
                    try:
                        shutil.copy2(fastapi_zip, zip_path)
                    except Exception:
                        pass
                if os.path.exists(zip_path):
                    return _mark_conversion_job_success_from_zip(job, zip_path, f"{tid}.zip")
        except Exception:
            pass

    return job


def conversion_job_status(request, task_id):
    """JSON status for an async conversion (poll from any page)."""
    job = get_object_or_404(ConversionJob, task_id=task_id)
    job = _resolve_pending_conversion_job(job)
    tid = str(job.task_id)
    if job.status == ConversionJob.STATUS_STARTED:
        return JsonResponse({"status": "started", "task_id": tid})
    if job.status == ConversionJob.STATUS_SUCCESS:
        dl = job.download_url or f"/download/{tid}/"
        return JsonResponse(
            {
                "status": "success",
                "task_id": tid,
                "download_url": dl,
            }
        )
    return JsonResponse(
        {
            "status": "error",
            "task_id": tid,
            "error": job.error_message or "Conversion failed",
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def gdal_callback(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    task_id = payload.get("task_id")
    status_value = payload.get("status")
    download_url = payload.get("download_url", "")
    output_zip_relpath = payload.get("output_zip_relpath", "")
    output_files_count = payload.get("output_files_count", 0)
    error_message = payload.get("error", "")

    if not task_id:
        return JsonResponse({"error": "missing task_id"}, status=400)

    try:
        job = ConversionJob.objects.get(task_id=task_id)
    except ConversionJob.DoesNotExist:
        return JsonResponse({"error": "job not found"}, status=404)

    if status_value == "completed":
        job.status = ConversionJob.STATUS_SUCCESS
        job.output_files_count = int(output_files_count or 0)
        if output_zip_relpath:
            job.output_zip_relpath = output_zip_relpath
        if download_url:
            job.download_url = download_url
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "output_files_count", "output_zip_relpath", "download_url", "finished_at"])
        zip_path = os.path.join(settings.MEDIA_ROOT, output_zip_relpath or f"{task_id}.zip")
        sync_conversion_job_completed(job, zip_path, output_files_count=job.output_files_count)
    elif status_value == "error":
        job.status = ConversionJob.STATUS_ERROR
        job.error_message = error_message or "GDAL processing failed"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        sync_conversion_job_failed(job, job.error_message)
    else:
        job.status = ConversionJob.STATUS_STARTED
        job.save(update_fields=["status"])

    return JsonResponse({"status": "ok"})


def convert_files(request):
    """Handle file uploads and conversion."""
    if request.method == 'POST':
        job = None
        task_dir = None
        try:
            input_format = request.POST.get('input_format')
            output_format = request.POST.get('output_format')
            conversion_crs = request.POST.get('crs', '').strip()
            remote_url = request.POST.get('remote_url', '').strip()
            upload_id = request.POST.get('upload_id', '').strip()
            source_crs = request.POST.get('source_crs', '').strip()

            if isinstance(input_format, str) and input_format.strip().lower() == 'all':
                input_format = 'Auto-detect'
            if isinstance(output_format, str) and output_format.strip().lower() == 'all':
                output_format = None

            input_format = _normalize_format_name(input_format)
            output_format = _normalize_format_name(output_format)
            
            files = request.FILES.getlist('files')
            if not files and not remote_url and not upload_id:
                return JsonResponse({'error': 'No files uploaded, upload_id, or remote URL provided'}, status=400)
                
            if input_format != 'Auto-detect' and input_format not in SUPPORTED_DRIVERS:
                return JsonResponse({'error': 'Invalid format specified'}, status=400)

            output_is_wildcard = output_format in (None, '', 'Auto-detect')
            if output_format and output_format not in SUPPORTED_DRIVERS:
                return JsonResponse({'error': 'Invalid format specified'}, status=400)

            input_ext = SUPPORTED_DRIVERS.get(input_format)
            output_ext = SUPPORTED_DRIVERS.get(output_format) if output_format else None
            
            # Create unique task folder
            task_id = str(uuid.uuid4())
            task_dir = os.path.join(settings.MEDIA_ROOT, task_id)
            input_dir = os.path.join(task_dir, 'input')
            output_dir = os.path.join(task_dir, 'output')
            
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)

            prj_missing = False
            total_size_bytes = 0

            # 1. Resumable Upload Case
            if upload_id:
                file_path_src = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.bin")
                meta_path_src = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.json")
                if not os.path.exists(file_path_src) or not os.path.exists(meta_path_src):
                    return JsonResponse({'error': 'Resumable upload session not found or expired.'}, status=400)
                
                with open(meta_path_src, 'r') as f_meta:
                    meta = json.load(f_meta)
                
                filename = meta["filename"]
                if check_path_traversal(filename):
                    return JsonResponse({'error': 'Path traversal attempt detected in filename.'}, status=400)
                
                total_size_bytes = meta["length"]
                file_path = os.path.join(input_dir, filename)
                shutil.move(file_path_src, file_path)
                try:
                    os.remove(meta_path_src)
                except Exception:
                    pass
                
                job = ConversionJob.objects.create(
                    task_id=task_id,
                    status=ConversionJob.STATUS_STARTED,
                    input_format=input_format or "",
                    output_format=output_format or "",
                    crs=conversion_crs or "",
                    upload_files_count=1,
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
                )
                ConversionInputFile.objects.create(
                    job=job,
                    original_name=filename,
                    size_bytes=total_size_bytes,
                    content_type=meta.get("metadata", {}).get("filetype", "application/octet-stream"),
                )

                # Validate
                validate_file_ext_and_mime(file_path, filename)
                if not scan_file_for_malware(file_path):
                    raise ValueError("File contains potential malware signature.")
                
                if file_path.lower().endswith('.zip'):
                    try:
                        zip_prj_missing = validate_shapefile_zip(file_path)
                        if zip_prj_missing:
                            prj_missing = True
                        with zipfile.ZipFile(file_path, 'r') as zip_ref:
                            zip_ref.extractall(input_dir)
                        os.remove(file_path)
                    except Exception as e:
                        raise ValueError(f"Failed to process ZIP archive: {str(e)}")

            # 2. Normal Upload Case
            elif files:
                total_size_bytes = sum(getattr(f, "size", 0) or 0 for f in files)
                if total_size_bytes > MAX_UPLOAD_SIZE:
                    return JsonResponse({'error': f"Total upload size exceeds limit of {format_bytes(MAX_UPLOAD_SIZE)}"}, status=400)
                
                try:
                    check_and_log_quota(request.user, request.META.get("REMOTE_ADDR"), total_size_bytes)
                except ValueError as quota_err:
                    return JsonResponse({'error': str(quota_err)}, status=429)

                job = ConversionJob.objects.create(
                    task_id=task_id,
                    status=ConversionJob.STATUS_STARTED,
                    input_format=input_format or "",
                    output_format=output_format or "",
                    crs=conversion_crs or "",
                    upload_files_count=len(files),
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
                )
                ConversionInputFile.objects.bulk_create(
                    [
                        ConversionInputFile(
                            job=job,
                            original_name=f.name,
                            size_bytes=getattr(f, "size", 0) or 0,
                            content_type=getattr(f, "content_type", "") or "",
                        )
                        for f in files
                    ]
                )

                for f in files:
                    if check_path_traversal(f.name):
                        raise ValueError(f"Path traversal attempt detected in filename: {f.name}")
                    
                    file_path = os.path.join(input_dir, f.name)
                    with open(file_path, 'wb+') as destination:
                        for chunk in f.chunks():
                            destination.write(chunk)
                    
                    # Validate
                    validate_file_ext_and_mime(file_path, f.name)
                    if not scan_file_for_malware(file_path):
                        raise ValueError(f"File '{f.name}' contains potential malware signature.")
                    
                    if file_path.lower().endswith('.zip'):
                        try:
                            zip_prj_missing = validate_shapefile_zip(file_path)
                            if zip_prj_missing:
                                prj_missing = True
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                zip_ref.extractall(input_dir)
                            os.remove(file_path)
                        except Exception as e:
                            raise ValueError(f"Failed to process ZIP archive: {str(e)}")

            # 3. Local path or remote URL ingestion case
            else:
                if is_local_input_path(remote_url):
                    local_source_path = normalize_local_input_path(remote_url)
                    local_source_is_file = os.path.isfile(local_source_path)
                    try:
                        copied_paths, local_size, local_file_count = copy_local_input_path(
                            remote_url,
                            input_dir,
                            MAX_UPLOAD_SIZE
                        )
                    except Exception as e:
                        return JsonResponse({'error': f"Local path import failed: {str(e)}"}, status=400)

                    try:
                        check_and_log_quota(request.user, request.META.get("REMOTE_ADDR"), local_size)
                    except ValueError as quota_err:
                        return JsonResponse({'error': str(quota_err)}, status=429)

                    job = ConversionJob.objects.create(
                        task_id=task_id,
                        status=ConversionJob.STATUS_STARTED,
                        input_format=input_format or "",
                        output_format=output_format or "",
                        crs=conversion_crs or "",
                        upload_files_count=local_file_count,
                        ip_address=request.META.get("REMOTE_ADDR"),
                        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
                    )
                    ConversionInputFile.objects.bulk_create(
                        [
                            ConversionInputFile(
                                job=job,
                                original_name=os.path.relpath(p, input_dir),
                                size_bytes=os.path.getsize(p) if os.path.isfile(p) else 0,
                                content_type="application/octet-stream",
                            )
                            for p in copied_paths
                            if os.path.isfile(p)
                        ]
                    )

                    for file_path in copied_paths:
                        if os.path.isfile(file_path):
                            if local_source_is_file:
                                validate_file_ext_and_mime(file_path, os.path.basename(file_path))
                            if not scan_file_for_malware(file_path):
                                raise ValueError(f"File '{os.path.basename(file_path)}' contains potential malware signature.")
                            if file_path.lower().endswith('.zip'):
                                try:
                                    zip_prj_missing = validate_shapefile_zip(file_path)
                                    if zip_prj_missing:
                                        prj_missing = True
                                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                        zip_ref.extractall(os.path.dirname(file_path))
                                    os.remove(file_path)
                                except Exception as e:
                                    raise ValueError(f"Failed to process ZIP archive: {str(e)}")
                else:
                    auth_headers = request.POST.get('auth_headers', '').strip()
                    expected_checksum = request.POST.get('expected_checksum', '').strip()
                    
                    try:
                        temp_path, checksum, fetched_size = ingest_remote_url(
                            remote_url,
                            auth_headers_str=auth_headers,
                            expected_checksum=expected_checksum,
                            max_size=MAX_UPLOAD_SIZE
                        )
                    except Exception as e:
                        return JsonResponse({'error': f"Remote fetch failed: {str(e)}"}, status=400)
                    
                    try:
                        check_and_log_quota(request.user, request.META.get("REMOTE_ADDR"), fetched_size)
                    except ValueError as quota_err:
                        os.remove(temp_path)
                        return JsonResponse({'error': str(quota_err)}, status=429)

                    parsed_url = urllib.parse.urlparse(remote_url)
                    filename = os.path.basename(parsed_url.path)
                    if not filename:
                        filename = "downloaded_data"
                    if check_path_traversal(filename):
                        os.remove(temp_path)
                        return JsonResponse({'error': 'Path traversal attempt detected in filename.'}, status=400)
                    
                    file_path = os.path.join(input_dir, filename)
                    shutil.move(temp_path, file_path)
                    
                    job = ConversionJob.objects.create(
                        task_id=task_id,
                        status=ConversionJob.STATUS_STARTED,
                        input_format=input_format or "",
                        output_format=output_format or "",
                        crs=conversion_crs or "",
                        upload_files_count=1,
                        ip_address=request.META.get("REMOTE_ADDR"),
                        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
                    )
                    ConversionInputFile.objects.create(
                        job=job,
                        original_name=filename,
                        size_bytes=fetched_size,
                        content_type="application/octet-stream",
                    )

                    # Validate
                    validate_file_ext_and_mime(file_path, filename)
                    if not scan_file_for_malware(file_path):
                        raise ValueError("File contains potential malware signature.")
                    
                    if file_path.lower().endswith('.zip'):
                        try:
                            zip_prj_missing = validate_shapefile_zip(file_path)
                            if zip_prj_missing:
                                prj_missing = True
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                zip_ref.extractall(input_dir)
                            os.remove(file_path)
                        except Exception as e:
                            raise ValueError(f"Failed to process ZIP archive: {str(e)}")

            # 4. Check for project/CRS requirements
            # Check if any .shp file is present and lacks .prj
            shp_files = []
            for root, dirs, filenames in os.walk(input_dir):
                for f in filenames:
                    if f.lower().endswith('.shp'):
                        shp_files.append(os.path.join(root, f))
            
            for shp in shp_files:
                base = os.path.splitext(shp)[0]
                if not os.path.exists(base + '.prj'):
                    prj_missing = True

            if job:
                job.prj_missing = prj_missing
                job.save(update_fields=['prj_missing'])

            if prj_missing and conversion_crs and not source_crs:
                raise ValueError("Shapefile ZIP is missing a .prj projection file. A manual source CRS assignment is required before a reprojection workflow can run.")

            # Add all files and directories in the task folder to saved_paths
            saved_paths = []
            for root, dirs, filenames in os.walk(input_dir):
                for filename in filenames:
                    saved_paths.append(os.path.join(root, filename))
                for dirname in dirs:
                    saved_paths.append(os.path.join(root, dirname))

            # Handle Auto-detect input format
            if input_format == 'Auto-detect':
                detected_driver = None
                detected_ext = None
                
                # Map of extension to driver (reverse of SUPPORTED_DRIVERS)
                ext_to_driver = {ext.lower(): drv for drv, ext in SUPPORTED_DRIVERS.items()}
                
                # Add common alternative extensions
                ext_to_driver['.jpeg'] = 'JPEG'
                ext_to_driver['.tiff'] = 'GTiff'
                ext_to_driver['.shp'] = 'ESRI Shapefile'
                ext_to_driver['.gdb'] = 'OpenFileGDB'
                ext_to_driver['.json'] = 'GeoJSON'
                
                for p in saved_paths:
                    ext = os.path.splitext(p)[1].lower()
                    if ext in ext_to_driver:
                        detected_driver = ext_to_driver[ext]
                        detected_ext = SUPPORTED_DRIVERS[detected_driver]
                        break
                    elif os.path.isdir(p) and p.lower().endswith('.gdb'):
                        detected_driver = 'OpenFileGDB'
                        detected_ext = '.gdb'
                        break
                
                if not detected_driver:
                    shutil.rmtree(task_dir)
                    return JsonResponse({'error': 'Could not automatically detect input format. Please specify it manually.'}, status=400)
                
                input_format = detected_driver
                input_ext = detected_ext
                print(f"[DEBUG] Auto-detected input format: {input_format} ({input_ext})")

            if output_is_wildcard:
                output_format = _default_output_format_for_input(input_format)
                if not output_format:
                    shutil.rmtree(task_dir)
                    return JsonResponse({'error': f'Unable to determine a default output format for {input_format}.'}, status=400)
                output_ext = SUPPORTED_DRIVERS[output_format]

            pair_validation = _validate_conversion_pair(input_format, output_format)
            if not pair_validation['valid']:
                return JsonResponse({
                    'error': pair_validation['reason'],
                    'allowed_outputs': pair_validation.get('allowed_outputs', []),
                }, status=400)

            if input_format == 'CSV':
                csv_validation_error = _validate_csv_spatial_input(saved_paths)
                if csv_validation_error:
                    shutil.rmtree(task_dir)
                    return JsonResponse({'error': csv_validation_error}, status=400)

            input_ext = SUPPORTED_DRIVERS.get(input_format)
            output_ext = SUPPORTED_DRIVERS[output_format]

            # Special handling for FileGDB
            if input_format == 'OpenFileGDB':
                has_gdb_dir = any(p.lower().endswith('.gdb') and os.path.isdir(p) for p in saved_paths)
                if not has_gdb_dir:
                    gdbtable_files = [p for p in saved_paths if p.lower().endswith('.gdbtable')]
                    if gdbtable_files:
                        new_gdb_dir = os.path.join(input_dir, "uploaded_data.gdb")
                        os.makedirs(new_gdb_dir, exist_ok=True)
                        source_dirs = set(os.path.dirname(p) for p in gdbtable_files)
                        for s_dir in source_dirs:
                            for f in os.listdir(s_dir):
                                if any(f.lower().endswith(ext) for ext in ['.gdbtable', '.gdbindexes', '.gdbtablx', '.atx', '.spx', '.freelist']):
                                    src_file = os.path.join(s_dir, f)
                                    if os.path.isfile(src_file):
                                        shutil.move(src_file, os.path.join(new_gdb_dir, f))
                        saved_paths = []
                        for root, dirs, filenames in os.walk(input_dir):
                            for filename in filenames:
                                saved_paths.append(os.path.join(root, filename))
                            for dirname in dirs:
                                saved_paths.append(os.path.join(root, dirname))

            matching_files = [p for p in saved_paths if path_matches_driver_ext(p, input_ext)]
            
            if not matching_files:
                available_exts = set()
                for p in saved_paths:
                    ext = os.path.splitext(p)[1].lower()
                    if ext: available_exts.add(ext)
                    elif os.path.isdir(p):
                        parts = os.path.basename(p).split('.')
                        if len(parts) > 1: available_exts.add('.' + parts[-1].lower())
                
                error_msg = f'No files match the selected input format "{input_format}" (expects {input_ext}). '
                error_msg += f'Uploaded extensions/folders: {sorted(list(available_exts))}. '
                shutil.rmtree(task_dir)
                return JsonResponse({'error': error_msg}, status=400)
                
            kwargs = {}
            if conversion_crs:
                kwargs['conversion_crs'] = conversion_crs
            if source_crs:
                kwargs['source_crs'] = source_crs

            if job:
                job.input_format = input_format or ""
                job.output_format = output_format or ""
                job.crs = conversion_crs or ""
                job.status = ConversionJob.STATUS_STARTED
                job.save(update_fields=["input_format", "output_format", "crs", "status"])
                sync_conversion_job_started(job)

            gdal_server_url = getattr(settings, "GDAL_SERVER_URL", "").strip()
            callback_url = request.build_absolute_uri("/gdal_callback/") if gdal_server_url else ""
            worker = threading.Thread(
                target=_conversion_worker,
                kwargs={
                    "task_id_str": task_id,
                    "task_dir": task_dir,
                    "input_dir": input_dir,
                    "output_dir": output_dir,
                    "input_format": input_format,
                    "input_ext": input_ext,
                    "output_format": output_format,
                    "output_ext": output_ext,
                    "batch_kwargs": kwargs,
                    "gdal_server_url": gdal_server_url,
                    "callback_url": callback_url,
                },
                daemon=True,
            )
            worker.start()

            return JsonResponse(
                {
                    "accepted": True,
                    "task_id": task_id,
                    "status": "started",
                    "download_url": f"/download/{task_id}/",
                    "prj_missing": prj_missing,
                },
                status=202,
            )

        except Exception as exc:
            try:
                if 'task_dir' in locals() and os.path.exists(task_dir):
                    shutil.rmtree(task_dir)
            except Exception:
                pass
            return JsonResponse({'error': str(exc)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

def preview_page(request):
    """Render the preview page."""
    task_id = request.GET.get('task_id', '')
    return render(request, 'converter/preview.html', {
        'active_page': 'preview',
        'task_id': task_id,
    })

def preview_data(request, task_id):
    """Generate and return preview data for a given conversion task with 1-hour cache TTL."""
    from django.core.cache import cache
    cache_key = f"preview_{task_id}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return JsonResponse(cached_data)

    job = get_object_or_404(ConversionJob, task_id=task_id)

    # If job not marked success in DB, attempt to locate a completed ZIP produced
    # by the FastAPI GDAL server as a fallback. If found, update the DB so the
    # preview can proceed even when the remote server didn't update the row.
    if job.status != ConversionJob.STATUS_SUCCESS:
        # Check expected Django MEDIA_ROOT ZIP first
        zip_path = os.path.join(settings.MEDIA_ROOT, f"{task_id}.zip")
        if os.path.exists(zip_path):
            job.status = ConversionJob.STATUS_SUCCESS
            job.output_zip_relpath = f"{task_id}.zip"
            job.download_url = f"/download/{task_id}/"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "output_zip_relpath", "download_url", "finished_at"])
        else:
            # Fallback: check FastAPI outputs folder for the task zip
            repo_root = os.path.normpath(os.path.join(str(settings.BASE_DIR), os.pardir))
            fastapi_zip = os.path.normpath(
                os.path.join(repo_root, 'gdal_server', 'outputs', str(task_id), f"{task_id}.zip")
            )
            if os.path.exists(fastapi_zip):
                # copy into MEDIA_ROOT so downstream code can read it consistently
                os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
                try:
                    shutil.copy2(fastapi_zip, zip_path)
                    job.status = ConversionJob.STATUS_SUCCESS
                    job.output_zip_relpath = f"{task_id}.zip"
                    job.download_url = f"/download/{task_id}/"
                    job.output_files_count = job.output_files_count or 0
                    job.finished_at = timezone.now()
                    job.save(update_fields=["status", "output_zip_relpath", "download_url", "finished_at", "output_files_count"])
                except Exception as e:
                    return JsonResponse({'error': f'Could not copy remote ZIP: {e}'}, status=500)
            else:
                return JsonResponse({'error': 'Conversion not ready'}, status=400)
    else:
        zip_path = os.path.join(settings.MEDIA_ROOT, f"{task_id}.zip")
        if not os.path.exists(zip_path):
            return JsonResponse({'error': 'Converted ZIP not found'}, status=404)

    import tempfile, zipfile
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmpdir)
            
            target_file = None
            is_raster = False
            
            # Find the output file recursively in the unzipped folder
            for root, _, files in os.walk(tmpdir):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in ['.tif', '.tiff', '.png', '.jpg', '.jpeg', '.pdf']:
                        target_file = os.path.join(root, f)
                        is_raster = True
                        break
                    elif ext in ['.shp', '.geojson', '.gpkg', '.kml', '.gdb', '.parquet', '.fgb', '.csv', '.dxf', '.arrow', '.feather', '.avro', '.gml']:
                        target_file = os.path.join(root, f)
                        break
                if target_file:
                    break
            
            if not target_file:
                # Check for .gdb folders specifically
                for root, dirs, _ in os.walk(tmpdir):
                    for d in dirs:
                        if d.endswith('.gdb'):
                            target_file = os.path.join(root, d)
                            break
                    if target_file:
                        break
                        
            if not target_file:
                # If there are files at all, let's just pick the first file that is not metadata (like .dbf, .shx, etc.)
                all_files = []
                for root, _, files in os.walk(tmpdir):
                    for f in files:
                        if not any(f.lower().endswith(ignored) for ignored in ['.dbf', '.shx', '.prj', '.cpg', '.sbx', '.sbn', '.xml']):
                            all_files.append(os.path.join(root, f))
                if all_files:
                    target_file = all_files[0]
                    # Guess if it is raster
                    ext = os.path.splitext(target_file)[1].lower()
                    if ext in ['.tif', '.tiff', '.png', '.jpg', '.jpeg', '.pdf']:
                        is_raster = True
                
            if not target_file:
                return JsonResponse({'error': 'No supported GIS files found in the output'}, status=404)

            preview_info = {
                'type': 'raster' if is_raster else 'vector',
                'file_name': os.path.basename(target_file),
            }

            if is_raster:
                import rasterio
                with rasterio.open(target_file) as src:
                    preview_info['bounding_box'] = list(src.bounds) if src.bounds else None
                    preview_info['crs'] = src.crs.to_string() if src.crs else 'Unknown'
                    preview_info['width'] = src.width
                    preview_info['height'] = src.height
                    preview_info['count'] = src.count
            else:
                import geopandas as gpd
                import pandas as pd
                import json
                

                # Robust reading
                ext = os.path.splitext(target_file)[1].lower()
                if ext == '.csv':
                    df = pd.read_csv(target_file)
                    try:
                        gdf = _read_csv_as_geodataframe(df)
                    except ValueError:
                        gdf = gpd.GeoDataFrame(df, geometry=None)
                elif ext == '.parquet':
                    gdf = gpd.read_parquet(target_file)
                elif ext in ['.arrow', '.feather']:
                    gdf = gpd.read_feather(target_file)
                elif ext == '.avro':
                    gdf = _read_custom_avro(target_file)
                else:
                    gdf = gpd.read_file(target_file)
                
                # Check for empty geometries
                if gdf.crs is None:
                    gdf = gdf.set_crs("EPSG:4326")
                
                try:
                    gdf_wgs84 = gdf.to_crs("EPSG:4326")
                except Exception:
                    gdf_wgs84 = gdf
                
                # Ensure we have geometries to calculate bounds, otherwise fallback
                has_geom = 'geometry' in gdf_wgs84.columns and gdf_wgs84.geometry.notna().any()
                bounds = gdf_wgs84.total_bounds.tolist() if has_geom else None
                feature_count = len(gdf_wgs84)
                
                limit = int(request.GET.get('limit', 100))
                limit = min(max(limit, 1), 1000)
                sample_gdf = gdf_wgs84.head(limit)
                
                schema = []
                for col in gdf.columns:
                    if col != 'geometry':
                        schema.append({'name': col, 'type': str(gdf[col].dtype)})
                
                # If no geometry, convert to geojson using dummy or empty geometry
                if not has_geom:
                    # Convert to empty point geometry so to_json works
                    from shapely.geometry import Point
                    sample_gdf = sample_gdf.copy()
                    sample_gdf['geometry'] = Point(0, 0)
                    sample_gdf = gpd.GeoDataFrame(sample_gdf, geometry='geometry', crs="EPSG:4326")
                
                geojson_str = sample_gdf.to_json()
                geojson_data = json.loads(geojson_str)

                # --- Data quality analysis (vector) ---
                def _calculate_vector_quality(gdf_full, sample):
                    issues = []
                    total = len(gdf_full) or 0

                    # Missing CRS
                    missing_crs = gdf_full.crs is None
                    if missing_crs:
                        issues.append({'code': 'missing_crs', 'message': 'Missing CRS', 'count': total})

                    # Invalid geometries
                    try:
                        valid_mask = gdf_full.geometry.is_valid.fillna(False)
                        invalid_count = int((~valid_mask).sum())
                    except Exception:
                        invalid_count = 0
                    if invalid_count:
                        issues.append({'code': 'invalid_geometry', 'message': 'Invalid geometries', 'count': invalid_count})

                    # Duplicate geometries (by geometry equality)
                    try:
                        dup_mask = gdf_full.geometry.duplicated()
                        dup_count = int(dup_mask.sum())
                    except Exception:
                        dup_count = 0
                    if dup_count:
                        issues.append({'code': 'duplicate_features', 'message': 'Duplicate features', 'count': dup_count})

                    # Empty attributes: rows where all non-geometry columns are null/empty
                    non_geom_cols = [c for c in gdf_full.columns if c != 'geometry']
                    empty_attr_count = 0
                    if non_geom_cols:
                        try:
                            attrs = gdf_full[non_geom_cols]
                            empties = attrs.isnull() | (attrs.applymap(lambda v: (isinstance(v, str) and v.strip()=='')))
                            empty_attr_count = int((empties.all(axis=1)).sum())
                        except Exception:
                            empty_attr_count = 0
                    if empty_attr_count:
                        issues.append({'code': 'empty_attributes', 'message': 'Empty attribute fields', 'count': empty_attr_count})

                    # Scoring: start at 100, subtract penalties
                    score = 100.0
                    if missing_crs:
                        score -= 30.0
                    if total:
                        invalid_pct = invalid_count / total
                        dup_pct = dup_count / total
                        empty_pct = empty_attr_count / total
                        score -= invalid_pct * 40.0
                        score -= dup_pct * 20.0
                        score -= empty_pct * 15.0

                    score = max(0, min(100, int(round(score))))
                    return score, issues

                quality_score, quality_issues = _calculate_vector_quality(gdf_wgs84, sample_gdf)

                preview_info.update({
                    'feature_count': feature_count,
                    'bounding_box': bounds,
                    'schema': schema,
                    'geojson': geojson_data,
                    'sample_count': len(sample_gdf),
                    'quality_score': quality_score,
                    'quality_issues': quality_issues,
                })

            cache.set(cache_key, preview_info, timeout=3600)
            return JsonResponse(preview_info)
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

def download_results(request, folder_id):
    """Serve the zipped converted files."""
    zip_path = os.path.join(settings.MEDIA_ROOT, f"{folder_id}.zip")
    if os.path.exists(zip_path):
        # Using FileResponse with a stream is safer and more efficient
        response = FileResponse(open(zip_path, 'rb'), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="converted_files.zip"'
        return response
    return HttpResponse("File not found", status=404)

def get_size_display(size_bytes):
    """Convert bytes to human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} KB"
    else:
        return f"{size_bytes/(1024**2):.1f} MB"

def is_binary(file_path):
    """Check if a file is binary."""
    try:
        with open(file_path, 'tr') as f:
            f.read(1024)
            return False
    except:
        return True

def search(request):
    """Search for files containing a keyword in input and output directories only."""
    query = request.GET.get('q', '').strip()
    
    # Define directories to search: MEDIA_ROOT (for tasks) and project root input folders
    search_dirs = [
        str(settings.MEDIA_ROOT),
        os.path.join(settings.BASE_DIR, 'test_in'),
        os.path.join(settings.BASE_DIR, 'test_input'),
        os.path.join(settings.BASE_DIR, 'test_input_2'),
        os.path.join(settings.BASE_DIR, 'test_input_3'),
        os.path.join(settings.BASE_DIR, 'test_matrix_in'),
    ]
    
    # Filter out non-existent directories and duplicates
    search_dirs = list(set([d for d in search_dirs if os.path.isdir(d)]))
    
    results = []
    
    if query:
        processed_files = set()
        for directory in search_dirs:
            try:
                for root, dirs, files in os.walk(directory):
                        
                    # Check if we are in an 'input' or 'output' folder (or test folders)
                    path_parts = os.path.normpath(root).split(os.sep)
                    is_in_target = any(part in ['input', 'output'] for part in path_parts)
                    
                    # Also include files directly from root input directories
                    is_root_input = root == directory and any(inp in directory for inp in ['test_in', 'test_input', 'test_matrix_in'])
                    
                    if not is_in_target and not is_root_input:
                        continue
                        
                    for file in files:
                        full_path = os.path.join(root, file)
                        if full_path in processed_files:
                            continue
                        processed_files.add(full_path)
                        
                        # Performance: Skip very large files (> 20MB) for text search
                        try:
                            file_size = os.path.getsize(full_path)
                            if file_size > 20 * 1024 * 1024:
                                continue
                        except:
                            continue
                        
                        if not is_binary(full_path):
                            try:
                                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    content_match = query.lower() in content.lower()
                                    name_match = query.lower() in file.lower()
                                    
                                    if content_match or name_match:
                                        stats = os.stat(full_path)
                                        g_info = get_gdal_info(full_path)
                                        
                                        # Display COMPLETE file content with ALL matches highlighted
                                        import re as regex_module
                                        if content_match:
                                            # Highlight all occurrences in the COMPLETE content
                                            full_content_highlighted = regex_module.sub(
                                                f'({regex_module.escape(query)})',
                                                r'<span class="highlight-word">\1</span>',
                                                content,
                                                flags=regex_module.IGNORECASE
                                            )
                                        else:
                                            # No highlights if only name matched
                                            full_content_highlighted = content

                                        results.append({
                                            'name': file,
                                            'path': full_path,
                                            'dir': root,
                                            'extension': os.path.splitext(file)[1],
                                            'size_display': get_size_display(stats.st_size),
                                            'size_bytes': stats.st_size,
                                            'modified': datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M'),
                                            'created': datetime.datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M'),
                                            'gdal_info': g_info,
                                            'full_content': full_content_highlighted,
                                            'is_binary': False,
                                            'match_type': 'Content' if content_match else 'Filename'
                                        })
                            except Exception:
                                pass
                        else:
                            # If binary, only check filename
                            if query.lower() in file.lower():
                                stats = os.stat(full_path)
                                g_info = get_gdal_info(full_path)
                                results.append({
                                    'name': file,
                                    'path': full_path,
                                    'dir': root,
                                    'extension': os.path.splitext(file)[1],
                                    'size_display': get_size_display(stats.st_size),
                                    'size_bytes': stats.st_size,
                                    'modified': datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M'),
                                    'created': datetime.datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M'),
                                    'gdal_info': g_info,
                                    'content_highlighted': '[Binary file - No preview available]',
                                    'is_binary': True,
                                    'match_type': 'Filename'
                                })
            except Exception:
                pass

        # Log search after we compute results (so results_count is accurate)
        try:
            SearchLog.objects.create(
                query=query,
                results_count=len(results),
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:512],
            )
        except Exception:
            # Never break UI if logging fails
            pass

    # Get recently converted files for the sidebar
    recent_files = []
    try:
        media_root = str(settings.MEDIA_ROOT)
        all_files = []
        for root, dirs, files in os.walk(media_root):
            path_parts = os.path.normpath(root).split(os.sep)
            # Only include files that are in an 'output' folder
            if 'output' in path_parts:
                for f in files:
                    full_p = os.path.join(root, f)
                    try:
                        all_files.append((full_p, os.path.getmtime(full_p)))
                    except:
                        continue
        
        # Sort by modification time, take top 10
        all_files.sort(key=lambda x: x[1], reverse=True)
        for p, mtime in all_files[:10]:
            recent_files.append({
                'name': os.path.basename(p),
                'path': p,
                'time': datetime.datetime.fromtimestamp(mtime).strftime('%H:%M %d/%m')
            })
    except:
        pass
    
    return render(request, 'converter/search.html', {
        'query': query,
        'results': results,
        'recent_files': recent_files,
        'active_page': 'search'
    })

def file_detail(request):
    """Display detailed information about a single file."""
    file_path = request.GET.get('path', '').strip()
    query = request.GET.get('q', '').strip()
    
    if not file_path or not os.path.isfile(file_path):
        return HttpResponse("File not found", status=404)
        
    try:
        stats = os.stat(file_path)
        extension = os.path.splitext(file_path)[1]
        
        file_info = {
            'name': os.path.basename(file_path),
            'path': file_path,
            'dir': os.path.dirname(file_path),
            'extension': extension,
            'size_display': get_size_display(stats.st_size),
            'size_bytes': stats.st_size,
            'modified': datetime.datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M'),
            'created': datetime.datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M'),
            'is_binary': is_binary(file_path),
            'gdal_info': get_gdal_info(file_path),
        }
        
        if not file_info['is_binary']:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read() # Read entire file content
                    if query:
                        # Simple highlighting using regex
                        highlighted = re.sub(f'({re.escape(query)})', r'<span class="highlight-word">\1</span>', content, flags=re.IGNORECASE)
                        file_info['content_highlighted'] = highlighted
                    else:
                        file_info['content_highlighted'] = content
            except Exception:
                file_info['is_binary'] = True
                
        return render(request, 'converter/file_detail.html', {
            'file_info': file_info,
            'query': query,
            'directory': os.path.dirname(file_path),
            'active_page': 'search'
        })
    except Exception as e:
        return HttpResponse(f"Error accessing file: {str(e)}", status=500)


class ConversionJobForm(forms.ModelForm):
    class Meta:
        model = ConversionJob
        fields = [
            "status",
            "error_message",
            "input_format",
            "output_format",
            "crs",
            "upload_files_count",
            "output_files_count",
            "download_url",
            "output_zip_relpath",
            "finished_at",
            "ip_address",
            "user_agent",
        ]
        widgets = {
            "error_message": forms.Textarea(attrs={"rows": 4}),
            "finished_at": forms.DateTimeInput(attrs={"placeholder": "YYYY-MM-DD HH:MM:SS"}),
            "user_agent": forms.TextInput(attrs={"maxlength": "512"}),
        }


class SearchLogForm(forms.ModelForm):
    class Meta:
        model = SearchLog
        fields = ["query", "results_count", "ip_address", "user_agent"]
        widgets = {"user_agent": forms.TextInput(attrs={"maxlength": "512"})}


def admin_panel(request):
    q = (request.GET.get("q") or "").strip()
    tab = (request.GET.get("tab") or "jobs").strip().lower()
    if tab not in {"jobs", "logs"}:
        tab = "jobs"

    jobs_qs = ConversionJob.objects.all()
    logs_qs = SearchLog.objects.all()

    if q:
        jobs_qs = jobs_qs.filter(
            Q(task_id__icontains=q)
            | Q(status__icontains=q)
            | Q(input_format__icontains=q)
            | Q(output_format__icontains=q)
            | Q(crs__icontains=q)
            | Q(error_message__icontains=q)
            | Q(ip_address__icontains=q)
            | Q(user_agent__icontains=q)
        )
        logs_qs = logs_qs.filter(Q(query__icontains=q) | Q(ip_address__icontains=q) | Q(user_agent__icontains=q))

    return render(
        request,
        "converter/admin_panel.html",
        {
            "active_page": "admin",
            "q": q,
            "tab": tab,
            "jobs": jobs_qs[:200],
            "logs": logs_qs[:200],
            "usage_dashboard": _build_usage_dashboard(),
        },
    )


def admin_job_detail(request, task_id):
    job = get_object_or_404(ConversionJob, task_id=task_id)
    return render(request, "converter/admin_job_detail.html", {"job": job, "active_page": ""})


def admin_job_edit(request, task_id):
    job = get_object_or_404(ConversionJob, task_id=task_id)
    if request.method == "POST":
        form = ConversionJobForm(request.POST, instance=job)
        if form.is_valid():
            form.save()
            return redirect("converter:admin_job_detail", task_id=job.task_id)
    else:
        form = ConversionJobForm(instance=job)
    return render(request, "converter/admin_edit.html", {"title": "Edit Conversion Job", "form": form, "active_page": ""})


def admin_job_create(request):
    if request.method == "POST":
        form = ConversionJobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            if not job.task_id:
                job.task_id = uuid.uuid4()
            job.save()
            return redirect("converter:admin_job_detail", task_id=job.task_id)
    else:
        form = ConversionJobForm(initial={'task_id': uuid.uuid4(), 'status': ConversionJob.STATUS_STARTED})
    return render(request, "converter/admin_edit.html", {"title": "Create Conversion Job", "form": form, "active_page": ""})


def admin_job_delete(request, task_id):
    job = get_object_or_404(ConversionJob, task_id=task_id)
    if request.method == "POST":
        job.delete()
        return redirect("converter:admin_panel")
    return render(
        request,
        "converter/admin_confirm_delete.html",
        {"title": "Delete Conversion Job", "object_name": str(job.task_id), "active_page": ""},
    )


def admin_log_detail(request, log_id):
    log = get_object_or_404(SearchLog, id=log_id)
    return render(request, "converter/admin_log_detail.html", {"log": log, "active_page": ""})


def admin_log_edit(request, log_id):
    log = get_object_or_404(SearchLog, id=log_id)
    if request.method == "POST":
        form = SearchLogForm(request.POST, instance=log)
        if form.is_valid():
            form.save()
            return redirect("converter:admin_log_detail", log_id=log.id)
    else:
        form = SearchLogForm(instance=log)
    return render(request, "converter/admin_edit.html", {"title": "Edit Search Log", "form": form, "active_page": ""})


def admin_log_create(request):
    if request.method == "POST":
        form = SearchLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            return redirect("converter:admin_log_detail", log_id=log.id)
    else:
        form = SearchLogForm()
    return render(request, "converter/admin_edit.html", {"title": "Create Search Log", "form": form, "active_page": ""})


def admin_log_delete(request, log_id):
    log = get_object_or_404(SearchLog, id=log_id)
    if request.method == "POST":
        log.delete()
        return redirect("converter:admin_panel",)
    return render(
        request,
        "converter/admin_confirm_delete.html",
        {"title": "Delete Search Log", "object_name": f'#{log.id} ("{log.query}")', "active_page": ""},
    )


def geojson_reader(request):
    """Display GeoJSON file with sidebar listing all features."""
    file_path = request.GET.get('path', '').strip()
    feature_index = request.GET.get('feature', None)
    
    if not file_path or not os.path.isfile(file_path):
        return HttpResponse("File not found", status=404)
    
    # Check if it's a GeoJSON file
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ['.json', '.geojson']:
        return HttpResponse("Not a valid GeoJSON file", status=400)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return HttpResponse(f"Error reading file: {str(e)}", status=500)
    
    # Extract features
    features = []
    if isinstance(data, dict) and 'features' in data:
        features = data['features']
    elif isinstance(data, list):
        features = data
    
    # Get file info
    stats = os.stat(file_path)
    file_info = {
        'name': os.path.basename(file_path),
        'path': file_path,
        'dir': os.path.dirname(file_path),
        'size_display': get_size_display(stats.st_size),
        'feature_count': len(features),
    }
    
    # Get selected feature details
    selected_feature = None
    if feature_index is not None:
        try:
            idx = int(feature_index)
            if 0 <= idx < len(features):
                selected_feature = features[idx]
                selected_feature['index'] = idx
        except (ValueError, IndexError):
            pass
    
    # If no feature selected but features exist, select first one
    if selected_feature is None and features:
        selected_feature = features[0]
        selected_feature['index'] = 0
    
    return render(request, 'converter/geojson_reader.html', {
        'file_info': file_info,
        'features': features,
        'selected_feature': selected_feature,
        'active_page': 'search',
    })


# ────────────────────────────────────────────────────────────────
# RASTER SPIKE - GeoTIFF Metadata, Reprojection & COG Conversion
# ────────────────────────────────────────────────────────────────

def raster_spike(request):
    """Raster Spike landing page - test GeoTIFF features."""
    return render(request, 'converter/raster_spike.html', {
        'active_page': 'raster_spike',
        'features': [
            {'name': 'GeoTIFF Metadata Extraction', 'description': 'Read technical details from raster files'},
            {'name': 'Raster Reprojection', 'description': 'Change map projection of raster data'},
            {'name': 'Cloud Optimized GeoTIFF (COG)', 'description': 'Convert to modern optimized formats'},
        ]
    })


@require_http_methods(['POST'])
def extract_raster_metadata(request):
    """
    Extract metadata from uploaded raster file.
    Returns: JSON with resolution, CRS, bands, extent, projection info
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)
        
        file = request.FILES['file']
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, file.name)
        
        # Save uploaded file temporarily
        with open(temp_path, 'wb+') as dest:
            for chunk in file.chunks():
                dest.write(chunk)
        
        # Extract metadata
        metadata = RasterMetadata(temp_path)
        summary = metadata.get_user_friendly_summary()
        
        return JsonResponse({
            'success': True,
            'filename': file.name,
            'metadata': metadata.to_dict(),
            'summary': summary
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_http_methods(['POST'])
def reproject_raster_file(request):
    """
    Reproject raster to different coordinate system.
    Parameters:
        - file: Raster file to reproject
        - target_crs: Target CRS (e.g., 'EPSG:3857')
        - resampling: Resampling method (nearest, bilinear, cubic, lanczos)
    """
    try:
        if 'file' not in request.FILES or 'target_crs' not in request.POST:
            return JsonResponse({'error': 'Missing file or target_crs'}, status=400)
        
        file = request.FILES['file']
        target_crs = request.POST.get('target_crs')
        resampling = request.POST.get('resampling', 'bilinear')
        
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        output_dir = os.path.join(settings.MEDIA_ROOT, 'raster_output')
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        input_path = os.path.join(temp_dir, file.name)
        output_name = os.path.splitext(file.name)[0] + '_reprojected.tif'
        output_path = os.path.join(output_dir, output_name)
        
        # Save uploaded file
        with open(input_path, 'wb+') as dest:
            for chunk in file.chunks():
                dest.write(chunk)
        
        # Reproject
        result_path = reproject_raster(input_path, output_path, target_crs, resampling)
        
        # Create download link
        download_url = f'/media/raster_output/{output_name}'
        
        return JsonResponse({
            'success': True,
            'message': f'Reprojected to {target_crs}',
            'output_file': output_name,
            'download_url': download_url
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_http_methods(['POST'])
def convert_to_cog_file(request):
    """
    Convert raster to Cloud Optimized GeoTIFF (COG).
    Parameters:
        - file: Raster file to convert
        - compression: Compression method (deflate, lzw, zstd, none)
    
    COG Benefits:
        - Faster cloud access via HTTP range requests
        - Better streaming performance
        - Efficient partial reading of large rasters
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)
        
        file = request.FILES['file']
        compression = request.POST.get('compression', 'deflate')
        
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        output_dir = os.path.join(settings.MEDIA_ROOT, 'raster_output')
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        input_path = os.path.join(temp_dir, file.name)
        output_name = os.path.splitext(file.name)[0] + '_cog.tif'
        output_path = os.path.join(output_dir, output_name)
        
        # Save uploaded file
        with open(input_path, 'wb+') as dest:
            for chunk in file.chunks():
                dest.write(chunk)
        
        # Convert to COG
        result_path = convert_to_cog(input_path, output_path, compression)
        
        # Create download link
        download_url = f'/media/raster_output/{output_name}'
        
        return JsonResponse({
            'success': True,
            'message': f'Converted to Cloud Optimized GeoTIFF with {compression} compression',
            'output_file': output_name,
            'download_url': download_url,
            'benefits': [
                'Faster cloud access (HTTP range requests)',
                'Better streaming performance',
                'Efficient partial reading of large rasters',
                'Optimized for COG-aware applications'
            ]
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_http_methods(['GET'])
def raster_formats_info(request):
    """Get information about supported raster formats and transformations."""
    supported_inputs = sorted({
        *VECTOR_TO_VECTOR.keys(),
        *RASTER_TO_RASTER.keys(),
        *VECTOR_TO_RASTER.keys(),
        *RASTER_TO_VECTOR.keys(),
    })
    return JsonResponse({
        'conversion_matrix': {
            'vector_to_vector': VECTOR_TO_VECTOR,
            'raster_to_raster': RASTER_TO_RASTER,
            'vector_to_raster': VECTOR_TO_RASTER,
            'raster_to_vector': RASTER_TO_VECTOR,
        },
        'format_aliases': FORMAT_ALIASES,
        'supported_outputs_by_input': {
            format_name: _get_supported_outputs(format_name)
            for format_name in supported_inputs
        },
        'raster_spike_features': {
            'metadata_extraction': {
                'name': 'GeoTIFF Metadata Extraction',
                'description': 'Read technical details from raster files',
                'extracts': ['Resolution', 'CRS', 'Bands', 'File size', 'Projection info', 'Geographic extent']
            },
            'reprojection': {
                'name': 'Raster Reprojection',
                'description': 'Convert raster data from one coordinate system to another',
                'example': 'EPSG:4326 → EPSG:3857',
                'resampling_methods': ['nearest', 'bilinear', 'cubic', 'lanczos']
            },
            'cog_conversion': {
                'name': 'Cloud Optimized GeoTIFF (COG)',
                'description': 'Convert raster files into modern optimized formats',
                'benefits': [
                    'Faster cloud access',
                    'Better streaming performance',
                    'HTTP range requests support',
                    'Efficient partial reading'
                ],
                'compression_options': ['deflate', 'lzw', 'zstd', 'none']
            }
        }
    })


# ────────────────────────────────────────────────────────────────
# DATABASE VIEWER — show all table data in the running project
# ────────────────────────────────────────────────────────────────

def database_viewer(request):
    from .models import (
        GeoFile, GeoFileLayer, Workflow, GeoProcessingJob, GeoProcessingJobLog,
        DestinationCredential, AuditLog, RbacRole, RbacPermission,
    )

    workflows    = list(Workflow.objects.all().order_by('id'))
    geo_files    = list(GeoFile.objects.all().order_by('id'))
    geo_layers   = list(GeoFileLayer.objects.all().order_by('id'))
    jobs         = list(GeoProcessingJob.objects.all().order_by('id'))
    job_logs     = list(GeoProcessingJobLog.objects.all().order_by('id'))
    audit_logs   = list(AuditLog.objects.all().order_by('id'))
    roles        = list(RbacRole.objects.all().order_by('id'))
    permissions  = list(RbacPermission.objects.all().order_by('id'))
    credentials  = list(DestinationCredential.objects.all().order_by('id'))

    total_records = (
        len(workflows) + len(geo_files) + len(geo_layers) +
        len(jobs) + len(job_logs) + len(audit_logs) +
        len(roles) + len(permissions) + len(credentials)
    )

    return render(request, 'converter/database_viewer.html', {
        'active_page':    'database_viewer',
        'workflows':      workflows,
        'geo_files':      geo_files,
        'geo_layers':     geo_layers,
        'jobs':           jobs,
        'job_logs':       job_logs,
        'audit_logs':     audit_logs,
        'roles':          roles,
        'permissions':    permissions,
        'credentials':    credentials,
        'total_records':  total_records,
        'table_count':    9,
    })


@csrf_exempt
@require_http_methods(['POST'])
def toggle_viewer_mode(request):
    """Toggle viewer mode in the user's session."""
    current = request.session.get('viewer_mode', False)
    request.session['viewer_mode'] = not current
    return JsonResponse({'viewer_mode': not current, 'success': True})


# ────────────────────────────────────────────────────────────────
# OPERATOR UI VIEWS & CONTROLLERS
# ────────────────────────────────────────────────────────────────

from .models import GeoFile, GeoFileLayer, Workflow, GeoProcessingJob, GeoProcessingJobLog, DispatchedLayer, DestinationCredential

def file_upload_page(request):
    """Render a file upload view supporting standard, remote URL, local path, and Tus uploads."""
    if request.method == "POST":
        source_type = request.POST.get('source_type', 'upload')

        # ── Local path ingestion ──────────────────────────────────
        if source_type == 'local':
            local_input = request.POST.get('local_path', '').strip()
            if local_input:
                try:
                    input_dir = make_upload_workspace()
                    copied_paths, total_size, file_count = copy_local_input_path(
                        local_input, input_dir, max_size=5 * 1024 * 1024 * 1024
                    )
                    # Use the first copied file (or directory root) as storage path
                    storage_path = copied_paths[0] if copied_paths else input_dir
                    name = os.path.basename(os.path.normpath(local_input))
                    geofile = GeoFile.objects.create(
                        original_file_name=name,
                        source_type='local',
                        file_type=os.path.splitext(name)[1].lower(),
                        mime_type='application/octet-stream',
                        storage_backend='local',
                        storage_path=storage_path,
                        size_bytes=total_size,
                        uploaded_by=request.user if request.user.is_authenticated else None,
                    )
                    return redirect('converter:operator_file_detail', file_id=geofile.id)
                except Exception as e:
                    return render(request, 'converter/operator_upload.html', {
                        'error': str(e), 'active_page': 'file_upload_page'
                    })

        # ── Remote URL ingestion ──────────────────────────────────
        elif source_type == 'remote':
            url = request.POST.get('remote_url', '').strip()
            if url:
                # Auto-detect local paths entered into the remote URL field
                if is_local_input_path(url):
                    try:
                        input_dir = make_upload_workspace()
                        copied_paths, total_size, file_count = copy_local_input_path(
                            url, input_dir, max_size=5 * 1024 * 1024 * 1024
                        )
                        storage_path = copied_paths[0] if copied_paths else input_dir
                        name = os.path.basename(os.path.normpath(url))
                        geofile = GeoFile.objects.create(
                            original_file_name=name,
                            source_type='local',
                            file_type=os.path.splitext(name)[1].lower(),
                            mime_type='application/octet-stream',
                            storage_backend='local',
                            storage_path=storage_path,
                            size_bytes=total_size,
                            uploaded_by=request.user if request.user.is_authenticated else None,
                        )
                        return redirect('converter:operator_file_detail', file_id=geofile.id)
                    except Exception as e:
                        return render(request, 'converter/operator_upload.html', {
                            'error': str(e), 'active_page': 'file_upload_page'
                        })
                else:
                    try:
                        local_path, checksum, dl_size = ingest_remote_url(url)
                        name = os.path.basename(local_path)
                        geofile = GeoFile.objects.create(
                            original_file_name=name,
                            source_type='remote',
                            source_url=url,
                            file_type=os.path.splitext(name)[1].lower(),
                            mime_type='application/octet-stream',
                            storage_backend='local',
                            storage_path=local_path,
                            size_bytes=dl_size,
                            checksum_sha256=checksum,
                            uploaded_by=request.user if request.user.is_authenticated else None,
                        )
                        return redirect('converter:operator_file_detail', file_id=geofile.id)
                    except Exception as e:
                        return render(request, 'converter/operator_upload.html', {
                            'error': str(e), 'active_page': 'file_upload_page'
                        })

        # ── Standard file upload ──────────────────────────────────
        else:
            uploaded_file = request.FILES.get('file')
            if uploaded_file:
                temp_dir = make_upload_workspace()
                original_name = os.path.basename(uploaded_file.name)
                if check_path_traversal(original_name):
                    return render(request, 'converter/operator_upload.html', {
                        'error': 'Invalid upload filename.', 'active_page': 'file_upload_page'
                    })
                dest_path = os.path.join(temp_dir, original_name)
                sha256 = hashlib.sha256()
                with open(dest_path, 'wb+') as dest:
                    for chunk in uploaded_file.chunks():
                        dest.write(chunk)
                        sha256.update(chunk)
                
                geofile = GeoFile.objects.create(
                    original_file_name=original_name,
                    source_type='upload',
                    file_type=os.path.splitext(original_name)[1].lower(),
                    mime_type=uploaded_file.content_type,
                    storage_backend='local',
                    storage_path=dest_path,
                    size_bytes=uploaded_file.size,
                    checksum_sha256=sha256.hexdigest(),
                    uploaded_by=request.user if request.user.is_authenticated else None,
                )
                return redirect('converter:operator_file_detail', file_id=geofile.id)
                
    return render(request, 'converter/operator_upload.html', {'active_page': 'file_upload_page'})


def file_list(request):
    """Display the list of geographic files uploaded in the system."""
    query = request.GET.get('q', '').strip()
    files = GeoFile.objects.all()
    if query:
        files = files.filter(original_file_name__icontains=query)
    return render(request, 'converter/operator_file_list.html', {
        'files': files,
        'query': query,
        'active_page': 'file_list'
    })


def operator_file_detail(request, file_id):
    """Detailed geographic metadata view for a GeoFile."""
    geofile = get_object_or_404(GeoFile, id=file_id)
    layers = geofile.layers.all()
    return render(request, 'converter/operator_file_detail.html', {
        'file': geofile,
        'layers': layers,
        'active_page': 'file_list'
    })


def file_validation_result(request, file_id):
    """Validation result view showing severity-graded list of issues."""
    geofile = get_object_or_404(GeoFile, id=file_id)
    issues = []
    
    # Simple validation rules
    if geofile.original_file_name.lower().endswith('.zip'):
        # Check zip contents for .shp missing .prj
        try:
            with zipfile.ZipFile(geofile.storage_path, 'r') as zip_ref:
                names = zip_ref.namelist()
                shp_files = [n for n in names if n.lower().endswith('.shp')]
                prj_files = [n for n in names if n.lower().endswith('.prj')]
                if shp_files and not prj_files:
                    issues.append({
                        'severity': 'error',
                        'code': 'MISSING_PRJ',
                        'message': 'Zip file contains .shp file but is missing spatial projection configuration (.prj file).'
                    })
        except Exception:
            issues.append({
                'severity': 'error',
                'code': 'INVALID_ZIP',
                'message': 'File is not a valid zip archive.'
            })
    
    # Check if layers have no EPSG
    for layer in geofile.layers.all():
        if not layer.source_crs_epsg:
            issues.append({
                'severity': 'warning',
                'code': 'MISSING_EPSG',
                'message': f"Layer '{layer.layer_name}' has no assigned EPSG coordinate system definition."
            })
            
    if not issues:
        issues.append({
            'severity': 'success',
            'code': 'VALID',
            'message': 'No critical format or spatial reference issues were found in the file structure.'
        })
        
    return render(request, 'converter/operator_validation.html', {
        'file': geofile,
        'issues': issues,
        'active_page': 'file_list'
    })


def assign_crs(request, file_id):
    """Assign or override Coordinate Reference System manually."""
    geofile = get_object_or_404(GeoFile, id=file_id)
    if request.method == "POST":
        epsg = request.POST.get('epsg', '').strip()
        if epsg:
            try:
                epsg_int = int(epsg)
                for layer in geofile.layers.all():
                    layer.source_crs_epsg = epsg_int
                    layer.source_crs_wkt = f"EPSG:{epsg_int}"
                    layer.save()
                return redirect('converter:operator_file_detail', file_id=geofile.id)
            except ValueError:
                return render(request, 'converter/operator_assign_crs.html', {
                    'file': geofile,
                    'error': 'EPSG code must be a valid integer.',
                    'active_page': 'file_list'
                })
    return render(request, 'converter/operator_assign_crs.html', {
        'file': geofile,
        'active_page': 'file_list'
    })


def workflow_catalog(request):
    """Workflow catalog listing active workflow definitions."""
    ensure_default_workflows()
    workflows = Workflow.objects.filter(is_active=True)
    file_id = request.GET.get('file', '')
    return render(request, 'converter/operator_workflows.html', {
        'workflows': workflows,
        'file_id': file_id,
        'active_page': 'workflow_catalog'
    })


def workflow_run(request, code):
    """Generate workflow parameter schema form and run workflow."""
    workflow = get_object_or_404(Workflow, code=code)
    file_id = request.GET.get('file', '')
    geofile = get_object_or_404(GeoFile, id=file_id) if file_id else None
    
    if request.method == "POST":
        parameters = {}
        # Simple binding parameters from schema keys
        for key in workflow.parameters_schema.keys():
            parameters[key] = request.POST.get(key, '')
            
        job = GeoProcessingJob.objects.create(
            workflow_code=workflow.code,
            status='pending',
            input_file=geofile,
            parameters=parameters,
            progress_percent=0,
            started_at=timezone.now(),
            requested_by=request.user if request.user.is_authenticated else None
        )
        # Dummy progress worker thread trigger
        def run_dummy_progress(job_id):
            import time
            try:
                j = GeoProcessingJob.objects.get(id=job_id)
                j.status = 'processing'
                j.progress_percent = 10
                j.save()
                GeoProcessingJobLog.objects.create(job=j, log_level='info', message='Started job execution.')
                
                time.sleep(2)
                j.progress_percent = 50
                j.save()
                GeoProcessingJobLog.objects.create(job=j, log_level='info', message='Successfully loaded inputs and metadata.')
                
                time.sleep(2)
                j.progress_percent = 90
                j.save()
                GeoProcessingJobLog.objects.create(job=j, log_level='info', message='Finished spatial coordinate transforms.')
                
                time.sleep(1)
                output_file = create_job_output_archive(j)
                j.status = 'completed'
                j.progress_percent = 100
                j.completed_at = timezone.now()
                j.output_file = output_file
                j.save(update_fields=['status', 'progress_percent', 'completed_at', 'output_file', 'updated_at'])
                GeoProcessingJobLog.objects.create(job=j, log_level='info', message=f'Job completed successfully. Output ready: {output_file.original_file_name}')
            except Exception as e:
                try:
                    j = GeoProcessingJob.objects.get(id=job_id)
                    j.status = 'failed'
                    j.save(update_fields=['status', 'updated_at'])
                    GeoProcessingJobLog.objects.create(job=j, log_level='error', message=f'Job failed: {str(e)}')
                except Exception:
                    pass
                
        threading.Thread(target=run_dummy_progress, args=(job.id,)).start()
        return redirect('converter:operator_job_detail', job_id=job.id)
        
    return render(request, 'converter/operator_workflow_run.html', {
        'workflow': workflow,
        'file': geofile,
        'active_page': 'workflow_catalog'
    })


def job_list(request):
    """Operator jobs listing view filterable by status."""
    status_filter = request.GET.get('status', '')
    jobs = GeoProcessingJob.objects.select_related('input_file', 'output_file').all()
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    return render(request, 'converter/operator_job_list.html', {
        'jobs': jobs,
        'status_filter': status_filter,
        'active_page': 'job_list'
    })


def operator_job_detail(request, job_id):
    """Live updating job status and progress view with HTMX support."""
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    if request.headers.get('hx-request') == 'true':
        # HTMX partial rendering
        return render(request, 'converter/partials/job_progress.html', {'job': job})
    return render(request, 'converter/operator_job_detail.html', {
        'job': job,
        'active_page': 'job_list'
    })


def job_preview_page(request, job_id):
    """Embedded React preview page for operator jobs."""
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    return render(request, 'converter/operator_job_preview.html', {
        'job': job,
        'active_page': 'job_list',
    })


def job_logs_view(request, job_id):
    """Job log viewer panel."""
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    logs = job.logs.all().order_by('created_at')
    return render(request, 'converter/operator_job_logs.html', {
        'job': job,
        'logs': logs,
        'active_page': 'job_list'
    })


PREVIEW_VECTOR_EXTENSIONS = {
    '.geojson', '.json', '.shp', '.gpkg', '.kml', '.gml', '.fgb',
    '.parquet', '.arrow', '.feather', '.avro'
}
PREVIEW_TABLE_EXTENSIONS = {'.csv'}


def _json_safe(value):
    if value is None:
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, float) and (value != value):
        return None
    return value


def _job_preview_archive(job):
    output_file = job.output_file
    if output_file and output_file.storage_path and os.path.isfile(output_file.storage_path):
        return output_file.storage_path
    if job.status == 'completed':
        return create_job_output_archive(job).storage_path
    raise FileNotFoundError("Job output is not ready for preview.")


def _first_preview_file(root_dir):
    candidates = []
    for root, _, filenames in os.walk(root_dir):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in PREVIEW_VECTOR_EXTENSIONS or ext in PREVIEW_TABLE_EXTENSIONS:
                candidates.append(os.path.join(root, filename))
    if not candidates:
        raise FileNotFoundError("No previewable vector or table file found in job output.")
    candidates.sort(key=lambda path: (os.path.splitext(path)[1].lower() not in ('.geojson', '.json'), path))
    return candidates[0]


def _with_job_preview_file(job, reader):
    archive_path = _job_preview_archive(job)
    if zipfile.is_zipfile(archive_path):
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(tmpdir)
            return reader(_first_preview_file(tmpdir))
    if os.path.isdir(archive_path):
        return reader(_first_preview_file(archive_path))
    return reader(archive_path)


def _read_geojson_preview(path, offset=0, limit=100):
    with open(path, 'r', encoding='utf-8') as source:
        data = json.load(source)
    features = data.get('features', []) if data.get('type') == 'FeatureCollection' else []
    sliced = features[offset:offset + limit]
    return {
        'name': os.path.basename(path),
        'feature_count': len(features),
        'bbox': data.get('bbox'),
        'schema': _schema_from_features(features),
        'features': {'type': 'FeatureCollection', 'features': sliced},
    }


def _schema_from_features(features):
    schema = {}
    for feature in features[:100]:
        for key, value in (feature.get('properties') or {}).items():
            if key not in schema:
                schema[key] = type(value).__name__
    return schema


def _read_tabular_preview(path, offset=0, limit=100):
    import pandas as pd
    df = pd.read_csv(path)
    page = df.iloc[offset:offset + limit]
    return {
        'name': os.path.basename(path),
        'feature_count': len(df),
        'bbox': None,
        'schema': {column: str(dtype) for column, dtype in df.dtypes.items()},
        'features': {'type': 'FeatureCollection', 'features': []},
        'rows': [
            {column: _json_safe(value) for column, value in row.items()}
            for row in page.to_dict(orient='records')
        ],
    }


def _read_vector_preview(path, offset=0, limit=100):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.geojson', '.json'):
        return _read_geojson_preview(path, offset, limit)
    if ext in PREVIEW_TABLE_EXTENSIONS:
        return _read_tabular_preview(path, offset, limit)

    import geopandas as gpd
    gdf = gpd.read_file(path, engine='pyogrio')
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        try:
            gdf = gdf.to_crs(4326)
        except Exception:
            pass
    page = gdf.iloc[offset:offset + limit]
    geojson = json.loads(page.to_json())
    bbox = None
    if not gdf.empty:
        bbox = [float(v) for v in gdf.total_bounds]
    return {
        'name': os.path.basename(path),
        'feature_count': len(gdf),
        'bbox': bbox,
        'schema': {column: str(dtype) for column, dtype in gdf.drop(columns=gdf.geometry.name).dtypes.items()},
        'features': geojson,
    }


def _job_preview_payload(job, offset=0, limit=100):
    return _with_job_preview_file(job, lambda path: _read_vector_preview(path, offset, limit))


def _pagination_params(request, default_page_size=25, max_page_size=100):
    page = max(int(request.GET.get('page', 1) or 1), 1)
    page_size = min(max(int(request.GET.get('page_size', default_page_size) or default_page_size), 1), max_page_size)
    return page, page_size, (page - 1) * page_size


def api_job_preview_summary(request, job_id):
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    try:
        payload = _job_preview_payload(job, 0, 1)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)
    return JsonResponse({
        'job_id': str(job.id),
        'workflow_code': job.workflow_code,
        'status': job.status,
        'source_file': payload['name'],
        'feature_count': payload['feature_count'],
        'bbox': payload['bbox'],
        'schema': payload['schema'],
        'preview_confirmed_at': job.preview_confirmed_at.isoformat() if job.preview_confirmed_at else None,
    })


def api_job_preview_features(request, job_id):
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    page, page_size, offset = _pagination_params(request, default_page_size=100, max_page_size=500)
    try:
        payload = _job_preview_payload(job, offset, page_size)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)
    features = payload['features']
    features['pagination'] = {
        'page': page,
        'page_size': page_size,
        'total': payload['feature_count'],
        'has_next': offset + page_size < payload['feature_count'],
        'has_previous': page > 1,
    }
    return JsonResponse(features)


def api_job_preview_attributes(request, job_id):
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    page, page_size, offset = _pagination_params(request)
    try:
        payload = _job_preview_payload(job, offset, page_size)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)
    rows = payload.get('rows')
    if rows is None:
        rows = [
            {key: _json_safe(value) for key, value in (feature.get('properties') or {}).items()}
            for feature in payload['features'].get('features', [])
        ]
    return JsonResponse({
        'columns': list(payload['schema'].keys()),
        'rows': rows,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': payload['feature_count'],
            'has_next': offset + page_size < payload['feature_count'],
            'has_previous': page > 1,
        },
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_job_confirm_preview(request, job_id):
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    job.preview_confirmed_at = timezone.now()
    job.preview_ready = True
    job.save(update_fields=['preview_confirmed_at', 'preview_ready', 'updated_at'])
    GeoProcessingJobLog.objects.create(job=job, log_level='info', message='Preview confirmed by operator.')
    return JsonResponse({'success': True, 'job_id': str(job.id), 'status': job.status})


@csrf_exempt
@require_http_methods(['POST'])
def api_job_abort_after_preview(request, job_id):
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    job.status = 'aborted'
    job.error_code = 'PREVIEW_ABORTED'
    job.error_message = 'Operator aborted the workflow after preview.'
    job.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])
    GeoProcessingJobLog.objects.create(job=job, log_level='warning', message='Workflow aborted after preview.')
    return JsonResponse({'success': True, 'job_id': str(job.id), 'status': job.status})


def output_list(request):
    """Legacy outputs route — completed jobs live on the Jobs page."""
    return redirect(f"{reverse('converter:job_list')}?status=completed")


def output_download(request, job_id):
    """Initiates output file download directly via a signed redirect."""
    job = get_object_or_404(GeoProcessingJob, id=job_id)
    output_file = job.output_file

    output_exists = bool(
        output_file
        and output_file.storage_path
        and os.path.isfile(output_file.storage_path)
    )
    if not output_exists and job.status == 'completed':
        try:
            output_file = create_job_output_archive(job)
            GeoProcessingJobLog.objects.create(job=job, log_level='info', message=f'Generated missing output archive: {output_file.original_file_name}')
        except Exception as e:
            return HttpResponse(f"Output file not generated or missing: {str(e)}", status=404)

    if output_file and output_file.storage_path and os.path.isfile(output_file.storage_path):
        return FileResponse(
            open(output_file.storage_path, 'rb'),
            as_attachment=True,
            filename=output_file.original_file_name,
        )
    return HttpResponse("Output file not generated or missing.", status=404)


def dispatched_layers_list(request):
    """Location export dispatch history."""
    layers = (
        DispatchedLayer.objects
        .filter(target_system='location_export')
        .select_related('job', 'job__input_file', 'job__output_file')
        .order_by('-dispatched_at', '-created_at')
    )
    return render(request, 'converter/operator_dispatched_list.html', {
        'layers': layers,
        'active_page': 'dispatched_layers_list'
    })


def dispatched_layer_detail(request, layer_id):
    """Dispatched layer detail screen."""
    layer = get_object_or_404(DispatchedLayer, id=layer_id)
    return render(request, 'converter/operator_dispatched_detail.html', {
        'layer': layer,
        'active_page': 'dispatched_layers_list'
    })


@csrf_exempt
@require_http_methods(['POST'])
def redispatch_action(request, layer_id):
    """Re-dispatch specific layer to the target endpoint without full page reload."""
    layer = get_object_or_404(DispatchedLayer, id=layer_id)
    layer.status = 'dispatched'
    layer.save()
    # Return custom HTMX inline status label
    return HttpResponse(
        '<span style="background-color: #0066cc; color: white; padding: 4px 8px; border-radius: 4px;">Re-dispatched Successfully</span>'
    )


# API endpoints matching notes
@csrf_exempt
@require_http_methods(['POST'])
def api_tus_upload(request):
    return tus_upload_init(request)


def api_output_download(request, job_id):
    return output_download(request, job_id)
