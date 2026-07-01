import os
import json
import base64
import zipfile
import tempfile
import shutil
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.utils import timezone

from converter.models import ConversionInputFile, ConversionJob, GeoFile, GeoProcessingJob, UploadQuotaLog
from converter.signals import DEFAULT_ORG_ID
from converter.batchconvert import path_matches_driver_ext
from converter.views import (
    validate_shapefile_zip,
    validate_file_ext_and_mime,
    check_path_traversal,
    ingest_remote_url,
    is_local_input_path,
    validate_remote_url,
    _validate_conversion_pair,
    TUS_UPLOAD_DIR,
)

class ShapefileValidationTests(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_zip(self, filenames):
        zip_path = os.path.join(self.test_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for name in filenames:
                zf.writestr(name, b"dummy content")
        return zip_path

    def test_valid_shapefile_zip(self):
        # ZIP with .shp, .shx, .dbf, and .prj
        zip_path = self.create_zip(["data.shp", "data.shx", "data.dbf", "data.prj"])
        prj_missing = validate_shapefile_zip(zip_path)
        self.assertFalse(prj_missing)

    def test_missing_dbf_rejects(self):
        # ZIP missing .dbf
        zip_path = self.create_zip(["data.shp", "data.shx", "data.prj"])
        with self.assertRaises(ValueError) as context:
            validate_shapefile_zip(zip_path)
        self.assertIn("missing required components", str(context.exception))

    def test_missing_prj_flags(self):
        # ZIP missing .prj (flags missing, returns True)
        zip_path = self.create_zip(["data.shp", "data.shx", "data.dbf"])
        prj_missing = validate_shapefile_zip(zip_path)
        self.assertTrue(prj_missing)


class GeoJsonExtensionTests(TestCase):
    def test_json_extension_allowed_for_geojson_driver(self):
        self.assertTrue(path_matches_driver_ext("/data/layer.json", ".geojson"))
        self.assertTrue(path_matches_driver_ext("/data/layer.geojson", ".geojson"))

    def test_validate_json_geojson_signature(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            handle.write(b'{"type": "FeatureCollection", "features": []}')
            path = handle.name
        try:
            validate_file_ext_and_mime(path, "layer.json")
        finally:
            os.unlink(path)


class ConversionMatrixTests(TestCase):
    def test_geojson_to_geopackage_allowed(self):
        result = _validate_conversion_pair("GeoJSON", "GeoPackage")
        self.assertTrue(result["valid"])

    def test_geotiff_raster_to_vector_limited(self):
        result = _validate_conversion_pair("GeoTIFF", "GeoPackage")
        self.assertFalse(result["valid"])
        self.assertIn("ESRI Shapefile", result["allowed_outputs"])
        self.assertIn("GeoJSON", result["allowed_outputs"])


class PathTraversalTests(TestCase):
    def test_safe_filenames(self):
        self.assertFalse(check_path_traversal("data.geojson"))
        self.assertFalse(check_path_traversal("my_shapefile.zip"))

    def test_unsafe_filenames(self):
        self.assertTrue(check_path_traversal("subfolder/file.shp"))
        self.assertTrue(check_path_traversal("../etc/passwd"))
        self.assertTrue(check_path_traversal("..\\..\\windows\\win.ini"))
        self.assertTrue(check_path_traversal("/absolute/path/file.txt"))


class RemoteIngestionTests(TestCase):
    def test_rejects_local_path_as_remote_url(self):
        with self.assertRaises(ValueError) as context:
            validate_remote_url(r"C:\Users\KAVAN\Downloads\converted_files (48)")
        self.assertIn("http:// or https://", str(context.exception))

    def test_detects_windows_path_as_local_input(self):
        self.assertTrue(is_local_input_path(r"C:\Users\KAVAN\Downloads\converted_files (48)"))

    @patch('requests.Session.head')
    @patch('requests.Session.get')
    def test_successful_fetch(self, mock_get, mock_head):
        # Mock head
        mock_head_resp = MagicMock()
        mock_head_resp.ok = True
        mock_head_resp.headers = {'Content-Length': '21'}
        mock_head.return_value = mock_head_resp

        # Mock get
        mock_get_resp = MagicMock()
        mock_get_resp.ok = True
        mock_get_resp.headers = {'Content-Length': '21'}
        mock_get_resp.iter_content.return_value = [b"geospatial data block"]
        mock_get.return_value = mock_get_resp

        temp_path, checksum, size = ingest_remote_url(
            "https://example.com/test.geojson",
            max_size=1024
        )
        self.assertTrue(os.path.exists(temp_path))
        self.assertEqual(size, len("geospatial data block"))
        os.remove(temp_path)

    @patch('requests.Session.head')
    @patch('requests.Session.get')
    def test_fetch_size_exceeded(self, mock_get, mock_head):
        # Mock head
        mock_head_resp = MagicMock()
        mock_head_resp.ok = True
        mock_head_resp.headers = {'Content-Length': '100'}
        mock_head.return_value = mock_head_resp

        # Mock get
        mock_get_resp = MagicMock()
        mock_get_resp.ok = True
        mock_get_resp.headers = {'Content-Length': '100'}
        mock_get_resp.iter_content.return_value = [b"a" * 100]
        mock_get.return_value = mock_get_resp

        with self.assertRaises(ValueError) as context:
            ingest_remote_url("https://example.com/large.zip", max_size=50)
        self.assertIn("exceeds maximum limit", str(context.exception))

    @patch('requests.Session.head')
    @patch('requests.Session.get')
    def test_checksum_validation(self, mock_get, mock_head):
        data = b"hello world"
        # Mock head
        mock_head_resp = MagicMock()
        mock_head_resp.ok = True
        mock_head_resp.headers = {'Content-Length': str(len(data))}
        mock_head.return_value = mock_head_resp

        # Mock get
        mock_get_resp = MagicMock()
        mock_get_resp.ok = True
        mock_get_resp.headers = {'Content-Length': str(len(data))}
        mock_get_resp.iter_content.return_value = [data]
        mock_get.return_value = mock_get_resp

        # Correct SHA-256 of "hello world"
        correct_sha = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        temp_path, checksum, size = ingest_remote_url(
            "https://example.com/data.txt",
            expected_checksum=correct_sha
        )
        self.assertEqual(checksum, correct_sha)
        os.remove(temp_path)

        # Incorrect checksum
        with self.assertRaises(ValueError) as context:
            ingest_remote_url(
                "https://example.com/data.txt",
                expected_checksum="wrongchecksum"
            )
        self.assertIn("Checksum mismatch", str(context.exception))


class ResumableUploadViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.init_url = reverse('converter:tus_upload_init')

    def test_initialize_upload(self):
        filename_b64 = base64.b64encode(b"test_raster.tif").decode()
        metadata = f"filename {filename_b64},filetype dGlm"
        
        response = self.client.post(
            self.init_url,
            HTTP_TUS_RESUMABLE="1.0.0",
            HTTP_UPLOAD_LENGTH="1000",
            HTTP_UPLOAD_METADATA=metadata
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.has_header("Location"))
        
        location = response["Location"]
        upload_id = location.rstrip('/').split('/')[-1]
        meta_file = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.json")
        self.assertTrue(os.path.exists(meta_file))
        
        # Clean up
        bin_file = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.bin")
        if os.path.exists(meta_file): os.remove(meta_file)
        if os.path.exists(bin_file): os.remove(bin_file)

    def test_patch_and_head_upload(self):
        filename_b64 = base64.b64encode(b"chunk.geojson").decode()
        metadata = f"filename {filename_b64}"
        response = self.client.post(
            self.init_url,
            HTTP_TUS_RESUMABLE="1.0.0",
            HTTP_UPLOAD_LENGTH="20",
            HTTP_UPLOAD_METADATA=metadata
        )
        upload_id = response["Location"].rstrip('/').split('/')[-1]
        
        patch_url = reverse('converter:tus_upload_chunk', kwargs={'upload_id': upload_id})
        
        # First chunk starts with '{' to satisfy geojson format check
        response_patch = self.client.patch(
            patch_url,
            data=b"{012345678",
            content_type="application/offset+octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0",
            HTTP_UPLOAD_OFFSET="0"
        )
        self.assertEqual(response_patch.status_code, 204)
        self.assertEqual(response_patch["Upload-Offset"], "10")

        # Head request
        response_head = self.client.head(
            patch_url,
            HTTP_TUS_RESUMABLE="1.0.0"
        )
        self.assertEqual(response_head.status_code, 200)
        self.assertEqual(response_head["Upload-Offset"], "10")

        # Second chunk
        response_patch2 = self.client.patch(
            patch_url,
            data=b"abcdefghij",
            content_type="application/offset+octet-stream",
            HTTP_TUS_RESUMABLE="1.0.0",
            HTTP_UPLOAD_OFFSET="10"
        )
        self.assertEqual(response_patch2.status_code, 204)
        self.assertEqual(response_patch2["Upload-Offset"], "20")

        # Clean up
        meta_file = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.json")
        bin_file = os.path.join(TUS_UPLOAD_DIR, f"{upload_id}.bin")
        if os.path.exists(meta_file): os.remove(meta_file)
        if os.path.exists(bin_file): os.remove(bin_file)


class AdminUsageDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_admin_panel_shows_usage_dashboard(self):
        user = User.objects.create_user(username='adminuser', password='pass12345')
        now = timezone.now()

        ConversionJob.objects.bulk_create([
            ConversionJob(
                task_id=uuid.uuid4(),
                status=ConversionJob.STATUS_ERROR,
                created_at=now,
                finished_at=now,
            )
        ])
        GeoFile.objects.bulk_create([
            GeoFile(
                org_id=DEFAULT_ORG_ID,
                original_file_name='sample.geojson',
                storage_path='/tmp/sample.geojson',
                size_bytes=2048,
                uploaded_by_id=user.id,
                created_at=now,
                updated_at=now,
            )
        ])
        UploadQuotaLog.objects.bulk_create([
            UploadQuotaLog(user=user, ip_address='127.0.0.1', size_bytes=2048)
        ])

        response = self.client.get(reverse('converter:admin_panel'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total uploads')
        self.assertContains(response, 'Failed jobs')
        self.assertContains(response, 'Storage usage')
        self.assertContains(response, 'adminuser')


class AdminJobDetailMinioTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.job = ConversionJob.objects.create(
            task_id=uuid.uuid4(),
            status=ConversionJob.STATUS_SUCCESS,
            upload_files_count=1,
            output_files_count=1,
            download_url='/download/sample/',
        )
        ConversionInputFile.objects.create(
            job=self.job,
            original_name='file_sorted_desc.geojson',
            size_bytes=2300000,
            content_type='application/geo+json',
        )

    @patch('converter.views.list_minio_objects')
    @patch('converter.views.get_minio_bucket_name', return_value='kavanmineshshah')
    @patch('converter.views.get_minio_object_prefix', return_value='conversion-jobs/sample/input')
    def test_admin_job_detail_shows_minio_object_list(self, mock_prefix, mock_bucket, mock_list):
        mock_list.return_value = [
            {
                'name': 'conversion-jobs/sample/input/file_sorted_desc.geojson',
                'size': 2300000,
                'last_modified': timezone.now(),
                'url': 'http://localhost:9000/kavanmineshshah/conversion-jobs/sample/input/file_sorted_desc.geojson',
            }
        ]

        response = self.client.get(reverse('converter:admin_job_detail', kwargs={'task_id': self.job.task_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'MinIO Objects')
        self.assertContains(response, 'file_sorted_desc.geojson')
        self.assertContains(response, 'kavanmineshshah')


class OperatorJobPreviewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.temp_dir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.temp_dir, 'sample.geojson')
        with open(self.input_path, 'w', encoding='utf-8') as target:
            json.dump({
                'type': 'FeatureCollection',
                'bbox': [72.0, 21.0, 73.0, 22.0],
                'features': [
                    {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [72.5, 21.5]},
                        'properties': {'name': 'A', 'value': 1},
                    },
                    {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [72.6, 21.6]},
                        'properties': {'name': 'B', 'value': 2},
                    },
                ],
            }, target)
        self.input_file = GeoFile.objects.create(
            original_file_name='sample.geojson',
            source_type='local',
            file_type='.geojson',
            mime_type='application/geo+json',
            storage_backend='local',
            storage_path=self.input_path,
            size_bytes=os.path.getsize(self.input_path),
        )
        self.stale_output = GeoFile.objects.create(
            original_file_name='missing.zip',
            source_type='local',
            file_type='.zip',
            mime_type='application/zip',
            storage_backend='local',
            storage_path=os.path.join(self.temp_dir, 'missing.zip'),
            size_bytes=0,
        )
        self.job = GeoProcessingJob.objects.create(
            workflow_code='preview-workflow',
            status='completed',
            input_file=self.input_file,
            output_file=self.stale_output,
            parameters={},
            progress_percent=100,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stale_output_download_regenerates_archive(self):
        response = self.client.get(reverse('converter:output_download', kwargs={'job_id': self.job.id}))
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertTrue(os.path.isfile(self.job.output_file.storage_path))

    def test_preview_summary_features_and_attributes(self):
        summary = self.client.get(reverse('converter:api_job_preview_summary', kwargs={'job_id': self.job.id}))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()['feature_count'], 2)

        features = self.client.get(reverse('converter:api_job_preview_features', kwargs={'job_id': self.job.id}), {'page': 1, 'page_size': 1})
        self.assertEqual(features.status_code, 200)
        self.assertEqual(len(features.json()['features']), 1)
        self.assertTrue(features.json()['pagination']['has_next'])

        attributes = self.client.get(reverse('converter:api_job_preview_attributes', kwargs={'job_id': self.job.id}), {'page': 2, 'page_size': 1})
        self.assertEqual(attributes.status_code, 200)
        self.assertEqual(attributes.json()['rows'][0]['name'], 'B')

    def test_confirm_and_abort_preview(self):
        confirmed = self.client.post(reverse('converter:api_job_confirm_preview', kwargs={'job_id': self.job.id}))
        self.assertEqual(confirmed.status_code, 200)
        self.job.refresh_from_db()
        self.assertTrue(self.job.preview_ready)
        self.assertIsNotNone(self.job.preview_confirmed_at)

        aborted = self.client.post(reverse('converter:api_job_abort_after_preview', kwargs={'job_id': self.job.id}))
        self.assertEqual(aborted.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'aborted')
