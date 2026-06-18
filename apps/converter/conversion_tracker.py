"""
Conversion Tracker - Automatically capture all 35+ fields when conversion happens
Records all data to SQL Server database tables
"""

import json
from datetime import datetime
from django.utils import timezone

from .models import (
    ConversionJob, GeoFile, GeoFileLayer, AuditLog, BatchTableDetails,
    DestinationCredential, RbacPrincipalRole
)
from .signals import DEFAULT_ORG_ID, log_audit_trail, log_batch_details


class ConversionTracker:
    """
    Automatically track and log all conversion activities with all 35+ fields
    Updates SQL Server database in real-time
    """
    
    def __init__(self, request=None, user=None, org_id=DEFAULT_ORG_ID):
        """
        Initialize tracker with request context
        
        Args:
            request: Django request object (for IP, user agent)
            user: Django user object
            org_id: Organization ID
        """
        self.request = request
        self.user = user
        self.org_id = org_id
        self.ip_address = self._get_ip_address()
        self.user_agent = self._get_user_agent()
        self.actor_id = self._get_actor_id()
        self.actor_type = self._get_actor_type()
        
    def _get_ip_address(self):
        """Extract IP address from request"""
        if not self.request:
            return '127.0.0.1'
        
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip or '127.0.0.1'
    
    def _get_user_agent(self):
        """Extract user agent from request"""
        if not self.request:
            return 'Unknown'
        return self.request.META.get('HTTP_USER_AGENT', 'Unknown')
    
    def _get_actor_id(self):
        """Get actor ID from user or default"""
        if self.user:
            return self.user.username or f'user_{self.user.id}'
        return 'system_process'
    
    def _get_actor_type(self):
        """Get actor type (USER, SYSTEM, API)"""
        if self.user and self.user.is_authenticated:
            return 'USER'
        return 'SYSTEM'
    
    def log_conversion_start(self, task_id, input_format, output_format, 
                            file_count=1, **extra_details):
        """
        Log conversion start event with all metadata
        
        Args:
            task_id: Unique conversion task ID
            input_format: Input file format (CSV, GeoJSON, etc)
            output_format: Output file format (PNG, GeoPackage, etc)
            file_count: Number of files being converted
            **extra_details: Any additional details to log
        """
        try:
            details = {
                'event': 'conversion_start',
                'task_id': str(task_id),
                'input_format': input_format,
                'output_format': output_format,
                'file_count': file_count,
                'timestamp': datetime.now().isoformat(),
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                name=f'Conversion {task_id}',
                table_name='conversion_jobs',
                codename='convert_file_start',
                app_label='converter',
                validationdomain_id=1,
                typecode='CONV_JOB',
                principal_id=self.actor_id,
                type='CONVERSION',
                role_id='converter',
                details=details
            )
            
            print(f"✅ Conversion start logged: {task_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging conversion start: {e}")
            return False
    
    def log_conversion_success(self, task_id, input_format, output_format,
                             input_files=1, output_files=1, **extra_details):
        """
        Log successful conversion completion
        """
        try:
            details = {
                'event': 'conversion_success',
                'task_id': str(task_id),
                'input_format': input_format,
                'output_format': output_format,
                'input_files': input_files,
                'output_files': output_files,
                'timestamp': datetime.now().isoformat(),
                'status': 'success',
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='UPDATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='UPDATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                name=f'Conversion {task_id} Success',
                table_name='conversion_jobs',
                codename='convert_file_success',
                app_label='converter',
                typecode='CONV_JOB_COMPLETE',
                principal_id=self.actor_id,
                type='CONVERSION',
                role_id='converter',
                details=details
            )
            
            print(f"✅ Conversion success logged: {task_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging conversion success: {e}")
            return False
    
    def log_conversion_error(self, task_id, error_message, **extra_details):
        """
        Log conversion error
        """
        try:
            details = {
                'event': 'conversion_error',
                'task_id': str(task_id),
                'error': error_message,
                'timestamp': datetime.now().isoformat(),
                'status': 'error',
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='UPDATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='UPDATE',
                resource_type='FILE_CONVERSION',
                resource_id=str(task_id),
                name=f'Conversion {task_id} Error',
                table_name='conversion_jobs',
                codename='convert_file_error',
                app_label='converter',
                typecode='CONV_JOB_ERROR',
                principal_id=self.actor_id,
                type='CONVERSION',
                role_id='converter',
                details=details
            )
            
            print(f"❌ Conversion error logged: {task_id} - {error_message}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging conversion error: {e}")
            return False
    
    def log_geo_file_upload(self, file_id, filename, file_type, file_size, **extra_details):
        """
        Log geo file upload
        """
        try:
            details = {
                'event': 'geo_file_upload',
                'filename': filename,
                'file_type': file_type,
                'size_bytes': file_size,
                'timestamp': datetime.now().isoformat(),
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='GEO_FILE',
                resource_id=str(file_id),
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='GEO_FILE',
                resource_id=str(file_id),
                name=filename,
                table_name='geo_files',
                codename='geo_file_upload',
                app_label='converter',
                typecode='GEO_FILE',
                principal_id=self.actor_id,
                type='FILE',
                role_id='uploader',
                details=details,
                file_id=file_id
            )
            
            print(f"✅ Geo file upload logged: {filename}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging geo file upload: {e}")
            return False
    
    def log_geo_layer_creation(self, layer_id, layer_name, geometry_type, 
                              feature_count, bbox, fields, has_z=False, 
                              has_mm=False, **extra_details):
        """
        Log geo layer creation with all geometry details
        """
        try:
            details = {
                'event': 'geo_layer_creation',
                'layer_name': layer_name,
                'geometry_type': geometry_type,
                'feature_count': feature_count,
                'bbox': bbox,
                'fields': fields,
                'has_z': has_z,
                'has_mm': has_mm,
                'timestamp': datetime.now().isoformat(),
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='GEO_LAYER',
                resource_id=str(layer_id),
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details with all geometry fields
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='GEO_LAYER',
                resource_id=str(layer_id),
                name=layer_name,
                table_name='geo_file_layers',
                codename='geo_layer_create',
                app_label='converter',
                typecode='GEO_LAYER',
                principal_id=self.actor_id,
                type='GEO',
                role_id='processor',
                details=details,
                file_id=None,
                geometry_type=geometry_type,
                has_z=has_z,
                has_mm=has_mm
            )
            
            print(f"✅ Geo layer creation logged: {layer_name}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging geo layer creation: {e}")
            return False
    
    def log_destination_credential(self, target_type, metadata, is_active=True, **extra_details):
        """
        Log destination credential setup
        """
        try:
            details = {
                'event': 'destination_setup',
                'target_type': target_type,
                'metadata': metadata,
                'is_active': is_active,
                'timestamp': datetime.now().isoformat(),
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='DESTINATION',
                resource_id=target_type,
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='DESTINATION',
                resource_id=target_type,
                name=f'Destination {target_type}',
                table_name='destination_credentials',
                codename='destination_setup',
                app_label='converter',
                typecode='DESTINATION',
                principal_id=self.actor_id,
                type='DESTINATION',
                role_id='admin',
                details=details
            )
            
            print(f"✅ Destination credential logged: {target_type}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging destination credential: {e}")
            return False
    
    def log_role_assignment(self, principal_id, role_id, principal_type='USER', **extra_details):
        """
        Log role assignment for RBAC
        """
        try:
            details = {
                'event': 'role_assignment',
                'principal_id': principal_id,
                'principal_type': principal_type,
                'role_id': role_id,
                'timestamp': datetime.now().isoformat(),
                **extra_details
            }
            
            # Log to audit log
            log_audit_trail(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='RBAC_ASSIGNMENT',
                resource_id=f'{principal_id}:{role_id}',
                details=details,
                ip_address=self.ip_address
            )
            
            # Log to batch table details
            log_batch_details(
                org_id=self.org_id,
                actor_type=self.actor_type,
                actor_id=self.actor_id,
                action='CREATE',
                resource_type='RBAC_ASSIGNMENT',
                resource_id=f'{principal_id}:{role_id}',
                name=f'Assign {role_id} to {principal_id}',
                table_name='rbac_principal_roles',
                codename='rbac_assign',
                app_label='converter',
                typecode='RBAC',
                principal_id=principal_id,
                type=principal_type,
                role_id=role_id,
                details=details
            )
            
            print(f"✅ Role assignment logged: {principal_id} → {role_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging role assignment: {e}")
            return False


# Usage example in views:
# tracker = ConversionTracker(request=request, user=request.user)
# tracker.log_conversion_start(task_id, 'CSV', 'GeoJSON', 3)
# ... do conversion ...
# tracker.log_conversion_success(task_id, 'CSV', 'GeoJSON', 3, 5)
