import json
import os
import sys
import traceback
import zipfile
from datetime import datetime, timezone

import requests
import re
import difflib
from django.http import JsonResponse, HttpResponse, FileResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .serializers import ConvertRequestSerializer

# Import batchconvert from the converter app
from converter.batchconvert import batch_convert, path_matches_driver_ext


BASE_DIR = os.path.dirname(__file__)
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)


_ALL_VECTOR_FORMATS = {"ESRI Shapefile", "GeoJSON", "GeoPackage", "KML", "KMZ", "OpenFileGDB", "DXF", "CSV", "FlatGeobuf", "GeoParquet", "GML", "Avro", "Arrow IPC"}

VECTOR_TO_VECTOR = {
    "ESRI Shapefile": {"GeoJSON", "GeoPackage", "KML", "KMZ", "GML", "CSV", "DXF", "FlatGeobuf", "GeoParquet", "Avro", "Arrow IPC", "OpenFileGDB"},
    "GeoJSON": {"ESRI Shapefile", "GeoPackage", "KML", "KMZ", "CSV", "DXF", "FlatGeobuf", "GeoParquet", "GML"},
    "GeoPackage": {"ESRI Shapefile", "GeoJSON", "KML", "KMZ", "DXF", "CSV", "FlatGeobuf", "GeoParquet", "GML", "OpenFileGDB"},
    "KML": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "CSV", "DXF"},
    "KMZ": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "CSV", "DXF"},
    "OpenFileGDB": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "CSV", "FlatGeobuf"},
    "DXF": {"ESRI Shapefile", "GeoJSON", "GeoPackage"},
    "CSV": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "KML"},
    "FlatGeobuf": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "GeoParquet"},
    "GeoParquet": {"ESRI Shapefile", "GeoJSON", "GeoPackage", "FlatGeobuf"},
    "GML": {"ESRI Shapefile", "GeoJSON", "GeoPackage"},
    "Avro": {"GeoJSON", "GeoPackage", "FlatGeobuf"},
    "Arrow IPC": {"GeoJSON", "GeoParquet", "GeoPackage"},
}

RASTER_TO_RASTER = {
    "GeoTIFF": {"PNG", "JPEG"},
    "GTiff": {"PNG", "JPEG"},
    "PNG": {"JPEG", "GeoTIFF", "GTiff"},
    "JPEG": {"PNG", "GeoTIFF", "GTiff"},
}

VECTOR_TO_RASTER = {
    "ESRI Shapefile": {"PNG", "JPEG", "GeoTIFF", "GTiff"},
    "GeoJSON": {"PNG", "JPEG", "GeoTIFF", "GTiff"},
    "GeoPackage": {"PNG", "JPEG", "GeoTIFF", "GTiff"},
    "KML": {"PNG", "JPEG"},
    "KMZ": {"PNG", "JPEG"},
    "DXF": {"PNG", "JPEG"},
}

RASTER_TO_VECTOR = {
    "PNG": {"ESRI Shapefile", "GeoJSON", "GeoPackage"},
    "JPEG": {"ESRI Shapefile", "GeoJSON"},
    "GeoTIFF": {"ESRI Shapefile", "GeoJSON"},
    "GTiff": {"ESRI Shapefile", "GeoJSON"},
}

SUPPORTED_CONVERSIONS = {
    **{src: {"vector": True, "targets": sorted(list(targets)), "kind": "vector-vector"} for src, targets in VECTOR_TO_VECTOR.items()},
    **{src: {"vector": False, "targets": sorted(list(targets)), "kind": "raster-raster"} for src, targets in RASTER_TO_RASTER.items()},
}

FORMAT_ALIASES = {
    "GTiff": "GeoTIFF",
    "opnfilegdb": "OpenFileGDB",
    "arrowipc": "Arrow IPC",
}


def _canonical_name(n: str) -> str:
    if not n:
        return n
    if n in FORMAT_ALIASES:
        return FORMAT_ALIASES[n]
    ln = n.lower()
    for k, v in FORMAT_ALIASES.items():
        if k.lower() == ln:
            return v
    for k in list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()):
        if k.lower() == ln:
            return k
    return n


def _format_kind(name: str) -> str:
    name = FORMAT_ALIASES.get(name, name)
    if name in VECTOR_TO_VECTOR or name in VECTOR_TO_RASTER:
        return "vector"
    if name in RASTER_TO_RASTER or name in RASTER_TO_VECTOR or name in {"GTiff", "PNG", "JPEG", "JPG"}:
        return "raster"
    return "unknown"


def _parse_requested_formats(raw: str) -> list:
    if not raw:
        return []
    known = set(list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()) + list(RASTER_TO_VECTOR.keys()) + list(VECTOR_TO_RASTER.keys()))
    canon_map = {k.lower(): k for k in known}
    parts = [p.strip() for p in str(raw).split(',') if p and p.strip()]
    results = []
    for p in parts:
        if not p:
            continue
        c = _canonical_name(p)
        if c in known:
            results.append(c)
            continue
        key = p.lower().strip()
        if key in canon_map:
            results.append(canon_map[key])
            continue
        close = difflib.get_close_matches(key, list(canon_map.keys()), n=1, cutoff=0.66)
        if close:
            results.append(canon_map[close[0]])
            continue
        cleaned = re.sub(r'[^a-z0-9]', '', key)
        found = False
        for k_lower, k_canon in canon_map.items():
            if k_lower.replace(' ', '').replace('-', '') in cleaned:
                results.append(k_canon)
                found = True
                break
        if found:
            continue
        results.append(p)
    return results


def _allowed_targets(input_driver: str) -> set[str]:
    input_driver = _canonical_name(input_driver)
    if input_driver in VECTOR_TO_VECTOR:
        return set(VECTOR_TO_VECTOR[input_driver]) | set(VECTOR_TO_RASTER.get(input_driver, set()))
    if input_driver in RASTER_TO_RASTER:
        return set(RASTER_TO_RASTER[input_driver]) | set(RASTER_TO_VECTOR.get(input_driver, set()))
    return set()


def _validate_conversion_pair(input_driver: str, output_driver: str) -> dict:
    input_list = _parse_requested_formats(input_driver) if isinstance(input_driver, str) else []
    if not input_list:
        return {"valid": False, "reason": "No input driver specified", "allowed_outputs": []}
    
    if any(str(i).strip().lower() == 'all' for i in input_list):
        all_inputs = set(list(VECTOR_TO_VECTOR.keys()) + list(RASTER_TO_RASTER.keys()))
        allowed = set()
        for inf in all_inputs:
            allowed.update(_allowed_targets(inf))
        allowed_list = sorted(list(allowed))
        if not output_driver:
            return {"valid": True, "allowed_outputs": allowed_list}
        requested_canon = _parse_requested_formats(output_driver)
        invalid = [o for o in requested_canon if o not in allowed]
        if invalid:
            return {
                "valid": False,
                "reason": f"Conversion from all to {', '.join(invalid)} is not supported.",
                "allowed_outputs": allowed_list,
            }
        return {"valid": True, "allowed_outputs": allowed_list}
    
    per_input_allowed = []
    for inf in input_list:
        canon_inf = _canonical_name(inf)
        outs = set(_allowed_targets(canon_inf))
        if not outs:
            return {"valid": False, "reason": f"Unsupported input driver: {inf}", "allowed_outputs": []}
        per_input_allowed.append(outs)
    
    common_allowed = set.intersection(*per_input_allowed) if per_input_allowed else set()
    allowed_list = sorted(list(common_allowed))
    if not output_driver:
        return {"valid": True, "allowed_outputs": allowed_list}
    requested_canon = _parse_requested_formats(output_driver)
    invalid = [o for o in requested_canon if o not in common_allowed]
    if invalid:
        return {
            "valid": False,
            "reason": f"Conversion from {', '.join(input_list)} to {', '.join(invalid)} is not supported.",
            "allowed_outputs": allowed_list,
        }
    return {"valid": True, "allowed_outputs": allowed_list}


SQLSERVER_HOST = os.getenv("SQLSERVER_HOST", ".\\SQLEXPRESS")
SQLSERVER_DATABASE = os.getenv("SQLSERVER_DATABASE", "kavanconverter")
SQLSERVER_DRIVER = os.getenv("SQLSERVER_DRIVER", "ODBC Driver 17 for SQL Server")


def _get_db_connection():
    import pyodbc
    conn_str = (
        f"DRIVER={{{SQLSERVER_DRIVER}}};"
        f"SERVER={SQLSERVER_HOST};"
        f"DATABASE={SQLSERVER_DATABASE};"
        "Trusted_Connection=yes;"
    )
    return pyodbc.connect(conn_str)


def _update_job_db(task_id: str, *, status: str, output_files_count: int | None = None,
                   output_zip_relpath: str | None = None, download_url: str | None = None,
                   error_message: str | None = None, finished: bool = False):
    set_parts: list[str] = ["status = ?"]
    params: list = [status]
    
    if output_files_count is not None:
        set_parts.append("output_files_count = ?")
        params.append(output_files_count)
    if output_zip_relpath is not None:
        set_parts.append("output_zip_relpath = ?")
        params.append(output_zip_relpath)
    if download_url is not None:
        set_parts.append("download_url = ?")
        params.append(download_url)
    if error_message is not None:
        set_parts.append("error_message = ?")
        params.append(error_message)
    if finished:
        set_parts.append("finished_at = ?")
        params.append(datetime.now(timezone.utc))
    
    params.append(task_id)
    sql = f"UPDATE conversion_jobs SET {', '.join(set_parts)} WHERE taskid = ?"
    
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()


def _create_dispatched_layer(task_id: str, target_system: str, status: str = "dispatched"):
    try:
        import uuid
        layer_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            sql = """
                INSERT INTO dispatched_layers (id, target_system, target_layer_id, status, dispatched_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql, layer_id, target_system, task_id, status, now, now)
            conn.commit()
        return layer_id
    except Exception as exc:
        traceback.print_exc()
        return None


def _fetch_job_db(task_id: str) -> dict | None:
    query = (
        "SELECT taskid, status, error_message, inputformat, outputformat, crs, "
        "upload_files_count, output_files_count, output_zip_relpath, download_url, "
        "prj_missing, quality_score, created_at, finished_at "
        "FROM conversion_jobs WHERE taskid = ?"
    )
    with _get_db_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(query, task_id).fetchone()
        if not row:
            return None
        return {
            "task_id": str(row.taskid),
            "status": row.status,
            "error_message": row.error_message,
            "input_format": row.inputformat,
            "output_format": row.outputformat,
            "crs": row.crs,
            "upload_files_count": row.upload_files_count,
            "output_files_count": row.output_files_count,
            "output_zip_relpath": row.output_zip_relpath,
            "download_url": row.download_url,
            "prj_missing": bool(row.prj_missing),
            "quality_score": row.quality_score,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }


def _validate_input_path(input_path: str, input_driver_ext: str) -> dict:
    if not os.path.exists(input_path):
        return {"valid": False, "reason": f"Input path not found: {input_path}"}
    
    if os.path.isdir(input_path):
        matched = []
        for root, _, filenames in os.walk(input_path):
            for filename in filenames:
                if path_matches_driver_ext(filename, input_driver_ext):
                    matched.append(os.path.join(root, filename))
        if not matched:
            return {
                "valid": False,
                "reason": f"No files with extension '{input_driver_ext}' were found in the input folder.",
                "hint": "Check the input folder and the selected input_driver_ext.",
                "matched_files": [],
            }
        return {"valid": True, "matched_files": matched, "kind": "directory"}
    
    if path_matches_driver_ext(input_path, input_driver_ext):
        return {"valid": True, "matched_files": [input_path], "kind": "file"}
    
    return {
        "valid": False,
        "reason": f"Input file does not match expected extension '{input_driver_ext}': {input_path}",
        "hint": "Verify the upload or choose Auto-detect in the main app.",
        "matched_files": [],
    }


def _task_dir(task_id: str) -> str:
    return os.path.join(OUTPUTS_DIR, task_id)


def _output_dir(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "output")


def _zip_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), f"{task_id}.zip")


def _django_media_zip_path(task_id: str) -> str:
    repo_root = os.path.normpath(os.path.join(BASE_DIR, os.pardir))
    return os.path.join(repo_root, "django_project", "media", f"{task_id}.zip")


def _existing_zip_path(task_id: str) -> str | None:
    for path in (_zip_path(task_id), _django_media_zip_path(task_id)):
        if os.path.exists(path):
            return path
    return None


def _status_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "status.json")


def _write_status(task_id: str, payload: dict) -> None:
    os.makedirs(_task_dir(task_id), exist_ok=True)
    with open(_status_path(task_id), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _collect_outputs(output_dir: str) -> list[str]:
    outputs: list[str] = []
    for root, _, filenames in os.walk(output_dir):
        for filename in filenames:
            outputs.append(os.path.relpath(os.path.join(root, filename), output_dir))
    return outputs


def _make_zip(task_id: str, output_dir: str) -> str:
    zip_path = _zip_path(task_id)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, filenames in os.walk(output_dir):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                arcname = os.path.relpath(file_path, output_dir).replace("\\", "/")
                zipf.write(file_path, arcname)
    return zip_path


def _run_conversion(req: dict) -> None:
    task_id = req["task_id"]
    output_dir = _output_dir(task_id)
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        _write_status(task_id, {"status": "running", "task_id": task_id})
        
        try:
            _update_job_db(task_id, status="started")
        except Exception:
            traceback.print_exc()
        
        validation = _validate_input_path(req["input_path"], req["input_driver_ext"])
        if not validation.get("valid"):
            raise RuntimeError(validation.get("reason", "Input validation failed"))
        
        print(f"[DEBUG] Conversion parameters:")
        print(f"  input_path: {req['input_path']}")
        print(f"  input_driver: {req['input_driver']}")
        print(f"  input_driver_ext: {req['input_driver_ext']}")
        print(f"  conversion_driver: {req['conversion_driver']}")
        print(f"  conversion_driver_ext: {req['conversion_driver_ext']}")
        print(f"  output_dir: {output_dir}")
        
        converted_files = batch_convert(
            input_path=req["input_path"],
            output_path=output_dir,
            input_driver=req["input_driver"],
            input_driver_ext=req["input_driver_ext"],
            conversion_driver=req["conversion_driver"],
            conversion_driver_ext=req["conversion_driver_ext"],
            **req.get("conversion_kwargs", {}),
        )
        
        print(f"[DEBUG] Converted files: {converted_files}")
        
        if not converted_files:
            raise RuntimeError(
                "No output files were produced. Check that the input path contains supported files and the selected input/output drivers are correct."
            )
        
        zip_path = _make_zip(task_id, output_dir)
        outputs = _collect_outputs(output_dir)
        download_url = f"/download/{task_id}"
        
        status_payload = {
            "status": "completed",
            "task_id": task_id,
            "output_files_count": len(outputs),
            "output_zip_relpath": os.path.basename(zip_path),
            "download_url": download_url,
            "outputs": outputs,
        }
        _write_status(task_id, status_payload)
        
        try:
            _update_job_db(
                task_id,
                status="success",
                output_files_count=len(outputs),
                output_zip_relpath=os.path.basename(zip_path),
                download_url=download_url,
                finished=True,
            )
            _create_dispatched_layer(task_id, target_system="download", status="success")
        except Exception:
            traceback.print_exc()
        
        if req.get("callback_url"):
            try:
                requests.post(req["callback_url"], json=status_payload, timeout=10)
            except Exception:
                traceback.print_exc()
    
    except Exception as exc:
        status_payload = {
            "status": "error",
            "task_id": task_id,
            "error": str(exc),
        }
        _write_status(task_id, status_payload)
        
        try:
            _update_job_db(
                task_id,
                status="error",
                error_message=str(exc)[:4000],
                finished=True,
            )
        except Exception:
            traceback.print_exc()
        
        if req.get("callback_url"):
            try:
                requests.post(req["callback_url"], json=status_payload, timeout=10)
            except Exception:
                traceback.print_exc()
        
        traceback.print_exc()


@api_view(['GET'])
def root(request):
    return HttpResponse("gdal server running successfully", content_type="text/plain")


@api_view(['GET'])
def app_info(request):
    return Response({
        "service": "GDAL Processing Server",
        "status": "GDAL server running successfully",
        "endpoints": {
            "health": "/health",
            "convert": "/convert",
            "status": "/status/{task_id}",
            "download": "/download/{task_id}",
        },
    })


@api_view(['GET'])
def health(request):
    db_ok = True
    db_error = ""
    try:
        with _get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)
    
    payload = {
        "status": "GDAL server running successfully",
        "database": {
            "server": SQLSERVER_HOST,
            "name": SQLSERVER_DATABASE,
            "connected": db_ok,
        },
    }
    if not db_ok:
        payload["database"]["error"] = db_error
    return Response(payload)


@api_view(['GET'])
def supported_conversions(request):
    return Response({
        "vector_to_vector": VECTOR_TO_VECTOR,
        "raster_to_raster": RASTER_TO_RASTER,
        "vector_to_raster": VECTOR_TO_RASTER,
        "raster_to_vector": RASTER_TO_VECTOR,
    })


@api_view(['POST'])
def convert(request):
    serializer = ConvertRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    req = serializer.validated_data
    os.makedirs(_task_dir(req["task_id"]), exist_ok=True)
    
    validation = _validate_input_path(req["input_path"], req["input_driver_ext"])
    pair_validation = _validate_conversion_pair(req["input_driver"], req["conversion_driver"])
    
    if not validation.get("valid"):
        return Response(
            {
                "accepted": False,
                "task_id": req["task_id"],
                "status": "error",
                "success": False,
                "message": validation.get("reason", "Input validation failed"),
                "validation": validation,
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not pair_validation.get("valid"):
        return Response(
            {
                "accepted": False,
                "task_id": req["task_id"],
                "status": "error",
                "success": False,
                "message": pair_validation.get("reason", "Unsupported conversion pair"),
                "validation": pair_validation,
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    queued_payload = {"status": "queued", "task_id": req["task_id"], "validation": validation}
    _write_status(req["task_id"], queued_payload)
    
    try:
        _update_job_db(req["task_id"], status="started")
    except Exception:
        traceback.print_exc()
    
    # Run conversion in background using threading
    import threading
    thread = threading.Thread(target=_run_conversion, args=(req,))
    thread.start()
    
    return Response({"accepted": True, "task_id": req["task_id"], "status": "queued", "validation": validation})


@api_view(['GET'])
def task_detail(request, task_id):
    db_task = _fetch_job_db(task_id)
    file_status = None
    try:
        status_path = _status_path(task_id)
        if os.path.exists(status_path):
            with open(status_path, "r", encoding="utf-8") as fh:
                file_status = json.load(fh)
    except Exception:
        traceback.print_exc()
    
    if not db_task and not file_status:
        zip_path = _existing_zip_path(task_id)
        if not zip_path:
            return Response({"error": "task not found"}, status=status.HTTP_404_NOT_FOUND)
        file_status = {
            "status": "completed",
            "task_id": task_id,
            "output_files_count": 1,
            "output_zip_relpath": os.path.basename(zip_path),
            "download_url": f"/download/{task_id}",
            "outputs": [os.path.basename(zip_path)],
            "source": "django_media" if zip_path == _django_media_zip_path(task_id) else "gdal_outputs",
        }
    
    status_value = (file_status or {}).get("status") or (db_task or {}).get("status")
    task_list = [
        "1. Submit conversion job from Django or directly to FastAPI.",
        "2. Validate input path and matching source files.",
        "3. Run GDAL conversion and create output ZIP.",
        "4. Update SQL Server job row with success or error details.",
        "5. Fetch the task detail endpoint and download the ZIP if successful.",
    ]
    
    detail = {
        "task_id": task_id,
        "status": status_value,
        "task_list": task_list,
        "validation": (file_status or {}).get("validation") or {},
        "database": db_task,
        "server_status": "GDAL server running successfully",
    }
    
    if file_status:
        detail["file_status"] = file_status
    
    if status_value == "error":
        detail["success"] = False
        detail["message"] = (file_status or {}).get("error") or (db_task or {}).get("error_message") or "Processing failed"
    else:
        detail["success"] = True if status_value in {"completed", "success"} else False
        if status_value in {"completed", "success"}:
            detail["message"] = "Conversion completed successfully"
    
    return Response(detail)


@api_view(['GET'])
def status(request, task_id):
    return task_detail(request, task_id)


@api_view(['GET'])
def download(request, task_id):
    path = _existing_zip_path(task_id)
    if not path:
        return Response({"error": "download not found"}, status=status.HTTP_404_NOT_FOUND)
    
    return FileResponse(path, filename=os.path.basename(path), content_type="application/zip")
