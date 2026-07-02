import uuid

from django.db import models
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField as PostgresJSONField
import json


# ============================================================================
# GEO FILES & LAYERS
# ============================================================================

class GeoFile(models.Model):
    """Model for storing uploaded geographic files"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True, null=True, blank=True)
    original_file_name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=20, choices=[('upload', 'Upload'), ('remote', 'Remote'), ('local', 'Local')])
    source_url = models.TextField(null=True, blank=True)
    file_type = models.CharField(max_length=100)
    mime_type = models.CharField(max_length=150)
    storage_backend = models.CharField(max_length=50)
    storage_path = models.TextField()
    size_bytes = models.BigIntegerField(null=True, blank=True, default=0)
    checksum_sha256 = models.CharField(max_length=64, blank=True, default='')
    uploaded_by = models.ForeignKey('auth.User', to_field='username', null=True, on_delete=models.SET_NULL, db_column='uploaded_by')
    created_at = models.DateTimeField(auto_now_add=True, db_column='created_at')
    updated_at = models.DateTimeField(auto_now=True, db_column='updated_at')

    class Meta:
        db_table = 'geo_files'
        ordering = ['-created_at']

    def __str__(self):
        return self.original_file_name


class GeoFileLayer(models.Model):
    """Model for storing layers within geo files"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(GeoFile, null=True, blank=True, on_delete=models.CASCADE, related_name='layers', db_column='file_id')
    layer_name = models.CharField(max_length=255)
    geometry_type = models.CharField(max_length=100)
    has_z = models.BooleanField(default=False)
    has_m = models.BooleanField(default=False)
    source_crs_epsg = models.IntegerField(null=True, blank=True)
    source_crs_wkt = models.TextField(null=True, blank=True)
    feature_count = models.BigIntegerField(default=0)
    bbox = models.JSONField()
    fields = models.JSONField()
    encoding = models.CharField(max_length=50)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'geo_file_layers'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.layer_name} (File: {self.file_id})"


# ============================================================================
# WORKFLOWS & PROCESSING JOBS
# ============================================================================

class Workflow(models.Model):
    """Model for storing workflow definitions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(unique=True, max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField()
    destination_type = models.CharField(max_length=50, choices=[
        ('download', 'Download'),
        ('feature_mapper', 'Feature Mapper'),
        ('webhook', 'External Webhook'),
        ('database', 'External Database'),
    ])
    parameters_schema = models.JSONField(default=dict, blank=True)
    preview_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workflows'
        ordering = ['name']

    def __str__(self):
        return self.name


class GeoProcessingJob(models.Model):
    """Model for storing geo processing jobs"""
    
    # Job status enum (FR-JOB-010)
    STATUS_CREATED = "created"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_AWAITING_PREVIEW = "awaiting_preview"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_PARTIAL = "partial"
    
    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_AWAITING_PREVIEW, "Awaiting Preview"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_PARTIAL, "Partial"),
    ]
    
    # Priority enum (FR-JOB-003)
    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True, null=True, blank=True)
    workflow_code = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    input_file = models.ForeignKey(GeoFile, null=True, on_delete=models.SET_NULL, related_name='input_jobs', db_column='input_file_id')
    output_file = models.ForeignKey(GeoFile, null=True, on_delete=models.SET_NULL, related_name='output_jobs', db_column='output_file_id')
    parameters = models.JSONField()
    progress_percent = models.IntegerField(default=0)
    preview_ready = models.BooleanField(default=False)
    preview_confirmed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    requested_by = models.ForeignKey('auth.User', to_field='username', null=True, on_delete=models.SET_NULL, db_column='requested_by')
    worker_hostname = models.CharField(max_length=100, null=True, blank=True, db_column='worker_id')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Celery task ID for tracking (FR-JOB-001)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        if self.idempotency_key == "":
            self.idempotency_key = None
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'geo_processing_jobs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['org_id', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='ux_jobs_idempotency',
            ),
        ]
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"Job {self.id} - {self.workflow_code} ({self.status})"


class GeoProcessingJobLog(models.Model):
    """Model for storing job processing logs"""
    LOG_LEVEL_CHOICES = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(GeoProcessingJob, null=True, blank=True, on_delete=models.CASCADE, related_name='logs', db_column='job_id')
    log_level = models.CharField(max_length=10, choices=LOG_LEVEL_CHOICES, default='info')
    message = models.TextField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_column='created_at', db_index=True)

    class Meta:
        db_table = 'geo_processing_job_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f"Log {self.id} - {self.log_level}"


# ============================================================================
# DISPATCHED LAYERS & CREDENTIALS
# ============================================================================

class DispatchedLayer(models.Model):
    """Model for storing dispatched layers to target systems"""
    STATUS_PENDING = "pending"
    STATUS_DISPATCHED = "dispatched"
    STATUS_CONFIRMED = "confirmed"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DISPATCHED, "Dispatched"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True, null=True, blank=True)
    job = models.ForeignKey(GeoProcessingJob, null=True, blank=True, on_delete=models.CASCADE, related_name='dispatches', db_column='job_id')
    target_system = models.CharField(max_length=100)
    target_layer_id = models.CharField(max_length=255, null=True, blank=True)
    target_endpoint = models.TextField(null=True, blank=True)
    target_database_fingerprint = models.CharField(max_length=64, null=True, blank=True)
    payload_metadata = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dispatched_layers'
        constraints = [
            models.UniqueConstraint(
                fields=['target_system', 'target_layer_id', 'target_database_fingerprint'],
                condition=models.Q(target_layer_id__isnull=False),
                name='ux_dispatched_target',
            ),
        ]

    def __str__(self):
        return f"Layer {self.target_layer_id} - {self.status}"


class DestinationCredential(models.Model):
    """Model for storing destination system credentials"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    target_type = models.CharField(max_length=50)
    encrypted_secret = models.BinaryField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'destination_credentials'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


# ============================================================================
# AUDIT & RBAC
# ============================================================================

class AuditLog(models.Model):
    """Model for storing audit logs"""
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('read', 'Read'),
        ('execute', 'Execute'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.CharField(max_length=36, db_index=True, null=True, blank=True)
    actor_type = models.CharField(max_length=20)
    actor_id = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=50, null=True, blank=True)
    resource_id = models.CharField(max_length=100, null=True, blank=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.actor_type}:{self.actor_id} - {self.action} {self.resource_type}"


class RbacRole(models.Model):
    """Model for storing RBAC roles"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = 'rbac_roles'
        ordering = ['name']

    def __str__(self):
        return self.name


class RbacPermission(models.Model):
    """Model for storing RBAC permissions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'rbac_permissions'
        ordering = ['code']

    def __str__(self):
        return self.code


class RbacRolePermission(models.Model):
    """Model for storing role-permission mappings"""
    id = models.BigAutoField(primary_key=True)
    role = models.ForeignKey(RbacRole, null=True, blank=True, on_delete=models.CASCADE, db_column='role_id')
    permission = models.ForeignKey(RbacPermission, null=True, blank=True, on_delete=models.CASCADE, db_column='permission_id')

    class Meta:
        db_table = 'rbac_role_permissions'
        unique_together = ('role', 'permission')

    def __str__(self):
        return f"Role {self.role_id} - Permission {self.permission_id}"


class RbacPrincipalRole(models.Model):
    """Model for storing principal-role mappings (users/groups to roles)"""
    id = models.BigAutoField(primary_key=True)
    PRINCIPAL_TYPE_CHOICES = [
        ('user', 'User'),
        ('group', 'Group'),
        ('org', 'Organization'),
    ]

    principal_id = models.CharField(max_length=100)
    principal_type = models.CharField(max_length=50, choices=PRINCIPAL_TYPE_CHOICES)
    role = models.ForeignKey(RbacRole, null=True, blank=True, on_delete=models.CASCADE, db_column='role_id')
    org_id = models.CharField(max_length=36, null=True, blank=True)

    class Meta:
        db_table = 'rbac_principal_roles'
        unique_together = ('principal_id', 'principal_type', 'role', 'org_id')

    def __str__(self):
        return f"{self.principal_type}:{self.principal_id} - Role {self.role_id}"


class BatchTableDetails(models.Model):
    """Model for storing batch table metadata and details"""
    table_name = models.CharField(max_length=255, db_column='table_name')
    actual_table_name = models.CharField(max_length=255, db_column='actual_table_name')
    org_id = models.CharField(max_length=36, db_column='org_id', null=True, blank=True)
    actor_type = models.CharField(max_length=50, db_column='actor_type', blank=True, default='')
    actor_id = models.IntegerField(db_column='actor_id', null=True, blank=True)
    action = models.CharField(max_length=50, db_column='action', blank=True, default='')
    resource_type = models.CharField(max_length=100, db_column='resource_type', blank=True, default='')
    resource_id = models.CharField(max_length=255, db_column='resource_id', blank=True, default='')
    details = models.TextField(db_column='details', blank=True, default='')
    ipaddress = models.GenericIPAddressField(db_column='ipaddress', null=True, blank=True)
    user_agent = models.CharField(max_length=512, db_column='user_agent', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_column='created_at')
    name = models.CharField(max_length=255, db_column='name', blank=True, default='')
    group_id = models.IntegerField(db_column='group_id', null=True, blank=True)
    permission = models.CharField(max_length=255, db_column='permission', blank=True, default='')
    content_type = models.CharField(max_length=100, db_column='content_type', blank=True, default='')
    codename = models.CharField(max_length=100, db_column='codename', blank=True, default='')
    void = models.BooleanField(db_column='void', default=False)
    ondelete = models.CharField(max_length=50, db_column='ondelete', blank=True, default='CASCADE')
    secret = models.TextField(db_column='secret', blank=True, default='')
    app_label = models.CharField(max_length=100, db_column='app_label', blank=True, default='')
    validation_domainid = models.CharField(max_length=255, db_column='validation_domainid', blank=True, default='')
    name_id = models.IntegerField(db_column='name_id', null=True, blank=True)

    class Meta:
        db_table = 'batch_table_details'
        ordering = ['-created_at']

    def __str__(self):
        return self.table_name


class SearchLog(models.Model):
    query = models.CharField(max_length=255, db_index=True, db_column='query')
    searched_at = models.DateTimeField(auto_now_add=True, db_index=True, db_column='searched_at')
    results_count = models.PositiveIntegerField(default=0, db_column='resultcount')
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_column='ipaddress')
    user_agent = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        ordering = ["-searched_at"]
        db_table = 'search_logs'

    def __str__(self) -> str:
        return f'"{self.query}" ({self.searched_at:%Y-%m-%d %H:%M:%S})'


class ConversionJob(models.Model):
    STATUS_STARTED = "started"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"

    STATUS_CHOICES = [
        (STATUS_STARTED, "Started"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_ERROR, "Error"),
    ]

    task_id = models.UUIDField(unique=True, db_index=True, db_column='taskid')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_column='created_at')
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True, db_column='finished_at')

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_STARTED, db_index=True, db_column='status')
    error_message = models.TextField(blank=True, default="")

    input_format = models.CharField(max_length=64, blank=True, default="", db_column='inputformat')
    output_format = models.CharField(max_length=64, blank=True, default="", db_column='outputformat')
    crs = models.CharField(max_length=64, blank=True, default="")

    upload_files_count = models.PositiveIntegerField(default=0)
    output_files_count = models.PositiveIntegerField(default=0)

    output_zip_relpath = models.CharField(max_length=512, blank=True, default="")
    download_url = models.CharField(max_length=512, blank=True, default="")

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    prj_missing = models.BooleanField(default=False)
    quality_score = models.IntegerField(null=True, blank=True, default=None)

    class Meta:
        ordering = ["-created_at"]
        db_table = 'conversion_jobs'

    def __str__(self) -> str:
        return f"{self.task_id} ({self.status})"


class ConversionInputFile(models.Model):
    job = models.ForeignKey(ConversionJob, on_delete=models.CASCADE, related_name="input_files")
    original_name = models.CharField(max_length=260)
    size_bytes = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.original_name


class LocationExport(models.Model):
    task_id = models.UUIDField(unique=True, db_index=True, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source_file_name = models.CharField(max_length=260, blank=True, default="")
    source_kind = models.CharField(max_length=16, blank=True, default="")
    output_format = models.CharField(max_length=64, blank=True, default="")
    geojson_geom = models.TextField(blank=True, default="")
    exported_count = models.PositiveIntegerField(default=0)
    download_url = models.CharField(max_length=512, blank=True, default="")
    output_zip_relpath = models.CharField(max_length=512, blank=True, default="")
    conversion_job_task_id = models.CharField(max_length=64, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # HMAC-SHA256 signature fields for send to export (FR-DISP-002)
    signature = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    signature_timestamp = models.DateTimeField(null=True, blank=True)
    signature_nonce = models.CharField(max_length=64, blank=True, null=True)
    signature_verified = models.BooleanField(default=False)  # Whether signature verification passed
    receiver_signature = models.CharField(max_length=255, blank=True, null=True)  # Receiver's recalculated signature
    payload_hash = models.CharField(max_length=64, blank=True, null=True, db_index=True)  # Hash of original payload for change detection

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.task_id} - {self.source_file_name}"


class UploadQuotaLog(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    size_bytes = models.BigIntegerField()

    class Meta:
        ordering = ["-uploaded_at"]
