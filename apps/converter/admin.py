from django.contrib import admin

from django.utils.html import format_html

from django.urls import reverse

from django.db.models import Q

from .models import (

    ConversionInputFile, ConversionJob, SearchLog,

    RbacRole, RbacPermission, RbacRolePermission, RbacPrincipalRole,

    BatchTableDetails, LocationExport

)

from converter.files.models import GeoFile, GeoFileLayer

from converter.workflows.models import Workflow, Job, JobLog

from converter.dispatch.models import DispatchedLayer, DestinationCredential

from converter.audit.models import AuditLog

import json





# ============================================================================

# CONVERSION & FILE MANAGEMENT

# ============================================================================



class ConversionInputFileInline(admin.TabularInline):

    model = ConversionInputFile

    extra = 0

    readonly_fields = ("original_name", "size_bytes", "content_type", "id")

    can_delete = False





@admin.register(ConversionJob)

class ConversionJobAdmin(admin.ModelAdmin):

    list_display = (

        "task_id_display",

        "status_badge",

        "input_format",

        "output_format",

        "upload_files_count",

        "output_files_count",

        "created_at",

        "finished_at",

        "ip_display",

    )

    list_filter = ("status", "created_at", "finished_at", "input_format", "output_format")

    search_fields = ("task_id", "ip_address", "user_agent", "error_message")

    readonly_fields = (

        "task_id", "created_at", "finished_at", "ip_address", "user_agent",

        "download_url", "error_message", "details_display"

    )

    fieldsets = (

        ("Task Information", {

            "fields": ("task_id", "status", "created_at", "finished_at")

        }),

        ("Format Details", {

            "fields": ("input_format", "output_format", "crs", "prj_missing")

        }),

        ("File Information", {

            "fields": ("upload_files_count", "output_files_count", "output_zip_relpath", "download_url")

        }),

        ("Request Details", {

            "fields": ("ip_address", "user_agent", "details_display")

        }),

        ("Error Information", {

            "fields": ("error_message",)

        }),

    )

    inlines = [ConversionInputFileInline]

    

    def task_id_display(self, obj):

        return str(obj.task_id)[:8] + "..."

    task_id_display.short_description = "Task ID"

    

    def status_badge(self, obj):

        colors = {

            'started': '#FFC300',

            'success': '#28a745',

            'error': '#dc3545',

        }

        color = colors.get(obj.status, '#6c757d')

        return format_html(

            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 3px;">{}</span>',

            color, obj.get_status_display()

        )

    status_badge.short_description = "Status"

    

    def ip_display(self, obj):

        return obj.ip_address or "N/A"

    ip_display.short_description = "IP Address"

    

    def details_display(self, obj):

        details = {

            'task_id': str(obj.task_id),

            'status': obj.status,

            'formats': f"{obj.input_format} → {obj.output_format}",

            'files': f"Input: {obj.upload_files_count}, Output: {obj.output_files_count}",

            'ip_address': obj.ip_address,

            'user_agent': obj.user_agent[:50] + '...' if obj.user_agent else 'N/A'

        }

        return format_html(

            '<pre style="background: #f5f5f5; padding: 10px; border-radius: 3px;">{}</pre>',

            json.dumps(details, indent=2)

        )

    details_display.short_description = "Details"





@admin.register(ConversionInputFile)

class ConversionInputFileAdmin(admin.ModelAdmin):

    list_display = ("original_name", "job_display", "size_display", "content_type")

    list_filter = ("content_type",)

    search_fields = ("original_name", "job__task_id")

    readonly_fields = ("original_name", "size_bytes", "content_type", "job")

    

    def job_display(self, obj):

        return str(obj.job.task_id)[:8] + "..."

    job_display.short_description = "Job ID"

    

    def size_display(self, obj):

        if obj.size_bytes is None:

            return "0.00 MB"

        size_mb = obj.size_bytes / (1024 * 1024)

        return f"{size_mb:.2f} MB"

    size_display.short_description = "File Size"





@admin.register(SearchLog)

class SearchLogAdmin(admin.ModelAdmin):

    list_display = ("query", "results_count", "searched_at", "ip_address", "user_agent_short")

    list_filter = ("searched_at", "results_count")

    search_fields = ("query", "ip_address", "user_agent")

    readonly_fields = ("query", "results_count", "searched_at", "ip_address", "user_agent")

    

    def user_agent_short(self, obj):

        return obj.user_agent[:50] + "..." if obj.user_agent else "N/A"

    user_agent_short.short_description = "User Agent"





# ============================================================================

# GEO FILES & LAYERS

# ============================================================================



@admin.register(GeoFile)

class GeoFileAdmin(admin.ModelAdmin):

    list_display = (

        "original_file_name",

        "file_type",

        "size_display",

        "org_id",

        "created_at",

        "uploaded_by",

    )

    list_filter = ("file_type", "created_at", "source_type")

    search_fields = ("original_file_name", "storage_path", "checksum_sha256")

    readonly_fields = ("created_at", "updated_at", "checksum_sha256", "size_display")

    fieldsets = (

        ("File Information", {

            "fields": ("original_file_name", "file_type", "mime_type", "size_display")

        }),

        ("Storage Details", {

            "fields": ("storage_backend", "storage_path", "checksum_sha256")

        }),

        ("Source Information", {

            "fields": ("source_type", "source_url", "org_id")

        }),

        ("Metadata", {

            "fields": ("created_at", "updated_at", "uploaded_by")

        }),

    )

    

    def size_display(self, obj):

        if obj.size_bytes is None:

            return "0.00 MB"

        size_mb = obj.size_bytes / (1024 * 1024)

        return f"{size_mb:.2f} MB"

    size_display.short_description = "File Size"





@admin.register(GeoFileLayer)

class GeoFileLayerAdmin(admin.ModelAdmin):

    list_display = (

        "layer_name",

        "file",

        "geometry_type",

        "feature_count",

        "has_z",

        "has_m",

        "created_at",

    )

    list_filter = ("geometry_type", "has_z", "has_m", "created_at")

    search_fields = ("layer_name", "source_crs_epsg")

    readonly_fields = ("created_at", "bbox_display", "fields_display", "metadata_display")

    fieldsets = (

        ("Layer Information", {

            "fields": ("file", "layer_name", "geometry_type")

        }),

        ("Geometry Details", {

            "fields": ("has_z", "has_m", "feature_count")

        }),

        ("Coordinate System", {

            "fields": ("source_crs_epsg", "source_crs_wkt")

        }),

        ("Data Details", {

            "fields": ("bbox_display", "fields_display", "encoding", "metadata_display")

        }),

        ("Timestamps", {

            "fields": ("created_at",)

        }),

    )

    

    def bbox_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.bbox)

    bbox_display.short_description = "Bounding Box"

    

    def fields_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.fields)

    fields_display.short_description = "Fields"

    

    def metadata_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.metadata)

    metadata_display.short_description = "Metadata"





# ============================================================================

# WORKFLOWS & PROCESSING

# ============================================================================



@admin.register(Workflow)

class WorkflowAdmin(admin.ModelAdmin):

    list_display = ("code", "name", "destination_type", "is_active", "preview_enabled", "created_at")

    list_filter = ("is_active", "preview_enabled", "destination_type")

    search_fields = ("code", "name", "description")

    readonly_fields = ("created_at", "parameters_schema_display")

    fieldsets = (

        ("Workflow Details", {

            "fields": ("code", "name", "description")

        }),

        ("Configuration", {

            "fields": ("destination_type", "preview_enabled", "is_active")

        }),

        ("Schema", {

            "fields": ("parameters_schema_display",)

        }),

        ("Timestamps", {

            "fields": ("created_at",)

        }),

    )

    

    def parameters_schema_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.parameters_schema)

    parameters_schema_display.short_description = "Parameters Schema"





@admin.register(Job)

class GeoProcessingJobAdmin(admin.ModelAdmin):

    list_display = (

        "job_id_display",

        "workflow_code",

        "status_badge",

        "priority",

        "progress_display",

        "created_at",

        "completed_at",

    )

    list_filter = ("status", "priority", "created_at", "workflow_code")

    search_fields = ("workflow_code", "error_message", "idempotency_key")

    readonly_fields = (

        "created_at", "updated_at", "progress_display", 

        "parameters_display", "error_details_display"

    )

    fieldsets = (

        ("Job Information", {

            "fields": ("workflow_code", "status", "priority", "org_id")

        }),

        ("Progress", {

            "fields": ("progress_display", "preview_ready", "preview_confirmed_at")

        }),

        ("Files", {

            "fields": ("input_file", "output_file")

        }),

        ("Parameters", {

            "fields": ("parameters_display",),

            "classes": ("collapse",)

        }),

        ("Execution", {

            "fields": ("started_at", "completed_at", "requested_by", "worker_hostname")

        }),

        ("Errors", {

            "fields": ("error_code", "error_details_display"),

            "classes": ("collapse",)

        }),

        ("Idempotency", {

            "fields": ("idempotency_key",)

        }),

        ("Timestamps", {

            "fields": ("created_at", "updated_at")

        }),

    )

    

    def job_id_display(self, obj):

        return f"Job #{obj.id}"

    job_id_display.short_description = "Job"

    

    def status_badge(self, obj):

        colors = {

            'pending': '#FFC300',

            'processing': '#0066cc',

            'completed': '#28a745',

            'failed': '#dc3545',

            'cancelled': '#6c757d',

        }

        color = colors.get(obj.status, '#6c757d')

        return format_html(

            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 3px;">{}</span>',

            color, obj.get_status_display()

        )

    status_badge.short_description = "Status"

    

    def progress_display(self, obj):

        return format_html(

            '<div style="width: 200px; background: #e9ecef; border-radius: 3px; overflow: hidden;">'

            '<div style="width: {}%; background: #28a745; color: white; text-align: center; line-height: 20px;">'

            '{}%</div></div>',

            obj.progress_percent, obj.progress_percent

        )

    progress_display.short_description = "Progress"

    

    def parameters_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.parameters)

    parameters_display.short_description = "Parameters"

    

    def error_details_display(self, obj):

        error_info = {

            'error_code': obj.error_code,

            'error_message': obj.error_message

        }

        return format_html('<pre style="background: #fff5f5; padding: 10px; color: #dc3545;">{}</pre>', 

                          json.dumps(error_info, indent=2))

    error_details_display.short_description = "Error Details"





@admin.register(JobLog)

class GeoProcessingJobLogAdmin(admin.ModelAdmin):

    list_display = ("job_id", "log_level_badge", "message_short", "created_at")

    list_filter = ("log_level", "created_at")

    search_fields = ("job_id", "message")

    readonly_fields = ("created_at", "details_display")

    fieldsets = (

        ("Log Information", {

            "fields": ("job", "log_level")

        }),

        ("Message", {

            "fields": ("message",)

        }),

        ("Details", {

            "fields": ("details_display",)

        }),

        ("Timestamp", {

            "fields": ("created_at",)

        }),

    )

    

    def log_level_badge(self, obj):

        colors = {

            'debug': '#6c757d',

            'info': '#0066cc',

            'warning': '#FFC300',

            'error': '#dc3545',

            'critical': '#721c24',

        }

        color = colors.get(obj.log_level, '#6c757d')

        return format_html(

            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',

            color, obj.get_log_level_display()

        )

    log_level_badge.short_description = "Level"

    

    def message_short(self, obj):

        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message

    message_short.short_description = "Message"

    

    def details_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.details)

    details_display.short_description = "Details"





# ============================================================================

# DISPATCHED LAYERS & CREDENTIALS

# ============================================================================



@admin.register(DispatchedLayer)

class DispatchedLayerAdmin(admin.ModelAdmin):

    list_display = (

        "target_layer_id",

        "job_id",

        "target_system",

        "status_badge",

        "dispatched_at",

    )

    list_filter = ("status", "target_system", "dispatched_at")

    search_fields = ("target_layer_id", "target_system")

    readonly_fields = ("created_at", "payload_display")

    fieldsets = (

        ("Dispatch Information", {

            "fields": ("job", "target_system", "target_layer_id", "status")

        }),

        ("Target Details", {

            "fields": ("target_endpoint", "target_database_fingerprint")

        }),

        ("Payload", {

            "fields": ("payload_display",)

        }),

        ("Timestamps", {

            "fields": ("dispatched_at", "created_at")

        }),

        ("Organization", {

            "fields": ("org_id",)

        }),

    )

    

    def status_badge(self, obj):

        colors = {

            'pending': '#FFC300',

            'dispatched': '#0066cc',

            'confirmed': '#28a745',

            'failed': '#dc3545',

        }

        color = colors.get(obj.status, '#6c757d')

        return format_html(

            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 3px;">{}</span>',

            color, obj.get_status_display()

        )

    status_badge.short_description = "Status"

    

    def payload_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.payload_metadata)

    payload_display.short_description = "Payload Metadata"





@admin.register(DestinationCredential)

class DestinationCredentialAdmin(admin.ModelAdmin):

    list_display = ("name", "target_type", "org_id", "created_at")

    list_filter = ("target_type", "created_at")

    search_fields = ("name", "target_type")

    readonly_fields = ("created_at", "updated_at", "metadata_display", "secret_masked")

    fieldsets = (

        ("Credential Information", {

            "fields": ("name", "target_type", "org_id")

        }),

        ("Secret", {

            "fields": ("secret_masked",),

            "classes": ("collapse",)

        }),

        ("Metadata", {

            "fields": ("metadata_display",)

        }),

        ("Timestamps", {

            "fields": ("created_at", "updated_at")

        }),

    )

    

    def secret_masked(self, obj):

        return "••••••••••••••••••••" if obj.encrypted_secret else "No secret"

    secret_masked.short_description = "Secret (Encrypted)"

    

    def metadata_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.metadata)

    metadata_display.short_description = "Metadata"





# ============================================================================

# AUDIT & RBAC

# ============================================================================



@admin.register(AuditLog)

class AuditLogAdmin(admin.ModelAdmin):

    list_display = (

        "actor_display",

        "action_badge",

        "resource_display",

        "ip_address",

        "created_at",

    )

    list_filter = ("action", "actor_type", "resource_type", "created_at")

    search_fields = ("resource_id", "ip_address", "actor_id")

    readonly_fields = ("created_at", "details_display")

    fieldsets = (

        ("Actor Information", {

            "fields": ("actor_type", "actor_id", "org_id")

        }),

        ("Action", {

            "fields": ("action",)

        }),

        ("Resource", {

            "fields": ("resource_type", "resource_id")

        }),

        ("Details", {

            "fields": ("details_display",)

        }),

        ("Network", {

            "fields": ("ip_address",)

        }),

        ("Timestamp", {

            "fields": ("created_at",)

        }),

    )

    

    def actor_display(self, obj):

        return f"{obj.actor_type} #{obj.actor_id}"

    actor_display.short_description = "Actor"

    

    def action_badge(self, obj):

        colors = {

            'create': '#0066cc',

            'update': '#FFC300',

            'delete': '#dc3545',

            'read': '#28a745',

            'execute': '#6f42c1',

        }

        color = colors.get(obj.action, '#6c757d')

        label = obj.action.replace('_', ' ').title() if obj.action else 'Unknown'

        return format_html(

            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',

            color, label

        )

    action_badge.short_description = "Action"

    

    def resource_display(self, obj):

        return f"{obj.resource_type} #{obj.resource_id}"

    resource_display.short_description = "Resource"

    

    def details_display(self, obj):

        return format_html('<pre style="background: #f5f5f5; padding: 10px;">{}</pre>', obj.details)

    details_display.short_description = "Details"





@admin.register(RbacRole)

class RbacRoleAdmin(admin.ModelAdmin):

    list_display = ("code", "name", "permissions_count")

    search_fields = ("code", "name")

    readonly_fields = ("permissions_count",)

    

    def permissions_count(self, obj):

        count = RbacRolePermission.objects.filter(role=obj).count()

        return count

    permissions_count.short_description = "Permissions Count"





@admin.register(RbacPermission)

class RbacPermissionAdmin(admin.ModelAdmin):

    list_display = ("code", "roles_count")

    search_fields = ("code",)

    readonly_fields = ("roles_count",)

    

    def roles_count(self, obj):

        count = RbacRolePermission.objects.filter(permission=obj).count()

        return count

    roles_count.short_description = "Roles Count"





@admin.register(RbacRolePermission)

class RbacRolePermissionAdmin(admin.ModelAdmin):

    list_display = ("role", "permission")

    list_filter = ("role",)

    search_fields = ("role__name", "permission__code")





@admin.register(RbacPrincipalRole)

class RbacPrincipalRoleAdmin(admin.ModelAdmin):

    list_display = ("principal_display", "principal_type", "role", "org_id")

    list_filter = ("principal_type", "role")

    search_fields = ("principal_id", "role__name")

    

    def principal_display(self, obj):

        return f"#{obj.principal_id}"

    principal_display.short_description = "Principal"





@admin.register(BatchTableDetails)

class BatchTableDetailsAdmin(admin.ModelAdmin):

    list_display = (

        "name",

        "table_name",

        "actual_table_name",

        "actor_type",

        "action",

        "created_at",

    )

    list_filter = ("table_name", "action", "created_at")

    search_fields = ("table_name", "actual_table_name", "name")

    readonly_fields = ("created_at",)

    fieldsets = (

        ("Table Information", {

            "fields": ("table_name", "actual_table_name", "name")

        }),

        ("Actor Information", {

            "fields": ("org_id", "actor_type", "actor_id")

        }),

        ("Resource", {

            "fields": ("resource_type", "resource_id", "action")

        }),

        ("Security", {

            "fields": ("void", "ondelete", "secret")

        }),

        ("Classification", {

            "fields": ("content_type", "codename", "app_label", "validation_domainid")

        }),

        ("Additional", {

            "fields": ("permission", "group_id", "name_id", "user_agent")

        }),

        ("Timestamp", {

            "fields": ("created_at",)

        }),

    )





@admin.register(LocationExport)

class LocationExportAdmin(admin.ModelAdmin):

    list_display = ("task_id_short", "source_file_name", "source_kind", "created_at")

    list_filter = ("source_kind", "created_at")

    search_fields = ("task_id", "source_file_name")

    readonly_fields = ("task_id", "created_at")

    

    def task_id_short(self, obj):

        return str(obj.task_id)[:8] + "..."

    task_id_short.short_description = "Task ID"





# ============================================================================

# AUTHORIZATION TOKENS

# ============================================================================

from rest_framework.authtoken.models import Token
from rest_framework.authtoken.admin import TokenAdmin as BaseTokenAdmin

# Unregister the default minimal Token admin provided by DRF (if it was registered)
try:
    admin.site.unregister(Token)
except admin.sites.NotRegistered:
    pass


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    """
    Rich admin view for DRF Authorization Tokens.
    Shows the full token key, allows copying, and links to the owning user.
    """

    list_display = (
        "user_display",
        "token_preview",
        "token_copy_button",
        "created",
    )

    search_fields = ("user__username", "user__email", "key")

    readonly_fields = (
        "key",
        "token_full_display",
        "created",
    )

    ordering = ("-created",)

    fieldsets = (
        ("User", {
            "fields": ("user",),
        }),
        ("Token", {
            "fields": ("key", "token_full_display", "created"),
            "description": (
                "The token key is shown in full below. "
                "Use it in the HTTP header: "
                "<code>Authorization: Token &lt;key&gt;</code>"
            ),
        }),
    )

    # ------------------------------------------------------------------
    # List display helpers
    # ------------------------------------------------------------------

    def user_display(self, obj):
        url = reverse("admin:auth_user_change", args=[obj.user_id])
        return format_html(
            '<a href="{}" style="font-weight:600;">{}</a>',
            url,
            obj.user.username,
        )

    user_display.short_description = "User"
    user_display.admin_order_field = "user__username"

    def token_preview(self, obj):
        """Show first 8 + last 8 chars with ••• in the middle."""
        key = obj.key
        if len(key) <= 16:
            preview = key
        else:
            preview = f"{key[:8]}••••••••{key[-8:]}"
        return format_html(
            '<code style="'
            "font-family: 'Courier New', monospace;"
            "background: #f0f4ff;"
            "border: 1px solid #c3d0f5;"
            "padding: 3px 8px;"
            "border-radius: 4px;"
            "font-size: 0.85em;"
            '">{}</code>',
            preview,
        )

    token_preview.short_description = "Token (preview)"

    def token_copy_button(self, obj):
        """Inline copy-to-clipboard button using a small JS snippet."""
        return format_html(
            '<button type="button" '
            'onclick="navigator.clipboard.writeText(\'{token}\').'
            "then(function(){{this.textContent='✓ Copied!';}}.bind(this),"
            "function(){{this.textContent='Copy failed';}})\" "
            'title="Copy full token to clipboard" '
            'style="'
            "cursor:pointer;"
            "background:#1a73e8;"
            "color:#fff;"
            "border:none;"
            "padding:4px 10px;"
            "border-radius:4px;"
            "font-size:0.8em;"
            "font-weight:600;"
            '">'
            "📋 Copy Token"
            "</button>",
            token=obj.key,
        )

    token_copy_button.short_description = "Actions"

    # ------------------------------------------------------------------
    # Detail page helper
    # ------------------------------------------------------------------

    def token_full_display(self, obj):
        """Render the full token key in a styled monospace box with a copy button."""
        return format_html(
            '<div style="'
            "display:flex;"
            "align-items:center;"
            "gap:10px;"
            "flex-wrap:wrap;"
            '">'
            '<code id="full-token-{uid}" style="'
            "font-family:'Courier New',monospace;"
            "background:#f0f4ff;"
            "border:1px solid #c3d0f5;"
            "padding:8px 14px;"
            "border-radius:6px;"
            "font-size:0.9em;"
            "word-break:break-all;"
            "flex:1;"
            '">{key}</code>'
            '<button type="button" '
            'onclick="navigator.clipboard.writeText(\'{key}\').'
            "then(function(){{this.textContent='✓ Copied!';}}.bind(this),"
            "function(){{this.textContent='Copy failed';}})\" "
            'style="'
            "cursor:pointer;"
            "background:#1a73e8;"
            "color:#fff;"
            "border:none;"
            "padding:7px 16px;"
            "border-radius:5px;"
            "font-weight:600;"
            "white-space:nowrap;"
            '">'
            "📋 Copy to Clipboard"
            "</button>"
            "</div>"
            '<p style="margin-top:8px;color:#555;font-size:0.85em;">'
            "<strong>Usage:</strong> Add to HTTP request header — "
            "<code>Authorization: Token {key}</code>"
            "</p>",
            uid=obj.pk,
            key=obj.key,
        )

    token_full_display.short_description = "Full Token Key"


# ============================================================================

# Customize admin site

# ============================================================================

admin.site.site_header = "Geo File Conversion Admin"

admin.site.site_title = "Conversion Management"

admin.site.index_title = "Welcome to Conversion Management Panel"

