"""
Django REST Framework views for GeoData Processor API.

This module implements DRF views with idempotency-key handling (FR-JOB-002).
"""

from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import GeoProcessingJob, GeoFile, Workflow
from .tasks import execute_workflow_job, cancel_job, confirm_preview


class IdempotencyMixin:
    """
    Mixin to handle idempotency-key deduplication within 24h (FR-JOB-002).
    
    This mixin checks for existing jobs with the same idempotency_key
    within the last 24 hours and returns the existing job if found.
    """
    
    def check_idempotency(self, request):
        """
        Check for existing job with same idempotency_key within 24h.
        
        Args:
            request: DRF request object
            
        Returns:
            Response with existing job if found, None otherwise
        """
        idempotency_key = request.headers.get('Idempotency-Key')
        
        if not idempotency_key:
            return None
        
        org_id = request.data.get('org_id') or request.query_params.get('org_id')
        
        # Check for existing job with same idempotency_key within 24h
        cutoff_time = timezone.now() - timedelta(hours=24)
        
        try:
            existing_job = GeoProcessingJob.objects.filter(
                idempotency_key=idempotency_key,
                org_id=org_id,
                created_at__gte=cutoff_time
            ).first()
            
            if existing_job:
                # Return existing job response
                return Response({
                    'id': str(existing_job.id),
                    'status': existing_job.status,
                    'workflow_code': existing_job.workflow_code,
                    'created_at': existing_job.created_at.isoformat(),
                    'message': 'Existing job found with same idempotency-key',
                    'is_duplicate': True,
                }, status=status.HTTP_200_OK)
                
        except Exception:
            pass
        
        return None


class JobViewSet(viewsets.ModelViewSet, IdempotencyMixin):
    """
    ViewSet for managing GeoProcessingJob instances.
    
    Implements FR-JOB-002: Idempotency-Key dedupe within 24h.
    """
    
    queryset = GeoProcessingJob.objects.all()
    
    def create(self, request, *args, **kwargs):
        """
        Create a new job with idempotency-key check.
        
        FR-JOB-002: Check for duplicate idempotency-key within 24h before creating.
        """
        # Check idempotency first
        idempotency_response = self.check_idempotency(request)
        if idempotency_response:
            return idempotency_response
        
        # Get idempotency-key from header
        idempotency_key = request.headers.get('Idempotency-Key')
        
        # Create job with idempotency-key
        data = request.data.copy()
        if idempotency_key:
            data['idempotency_key'] = idempotency_key
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # Trigger Celery task (FR-JOB-001)
        job = serializer.instance
        task = execute_workflow_job.delay(str(job.id))
        
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        Cancel a running job (FR-JOB-005).
        
        Uses Celery's revoke with terminate=True.
        """
        job = self.get_object()
        
        if job.status not in [GeoProcessingJob.STATUS_QUEUED, GeoProcessingJob.STATUS_RUNNING]:
            return Response(
                {'error': f'Cannot cancel job in status: {job.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        result = cancel_job.delay(str(job.id))
        
        return Response(result.get())
    
    @action(detail=True, methods=['post'])
    def confirm_preview(self, request, pk=None):
        """
        Confirm or abort a preview (FR-JOB-010).
        
        Args:
            confirmed: Boolean to confirm (True) or abort (False)
        """
        job = self.get_object()
        
        if job.status != GeoProcessingJob.STATUS_AWAITING_PREVIEW:
            return Response(
                {'error': f'Job is not in awaiting_preview status: {job.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        confirmed = request.data.get('confirmed', True)
        result = confirm_preview.delay(str(job.id), confirmed)
        
        return Response(result.get())


class JobCreateView(APIView, IdempotencyMixin):
    """
    Simple API view for creating jobs with idempotency support.
    
    This is a simpler alternative to the ViewSet for job creation.
    """
    
    def post(self, request):
        """
        Create a new job with idempotency-key check.
        
        FR-JOB-002: Check for duplicate idempotency-key within 24h before creating.
        """
        # Check idempotency first
        idempotency_response = self.check_idempotency(request)
        if idempotency_response:
            return idempotency_response
        
        # Get idempotency-key from header
        idempotency_key = request.headers.get('Idempotency-Key')
        
        # Create job
        data = request.data
        
        # Validate required fields
        required_fields = ['workflow_code', 'parameters']
        for field in required_fields:
            if field not in data:
                return Response(
                    {'error': f'Missing required field: {field}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Set priority based on file size (FR-JOB-003)
        priority = data.get('priority', GeoProcessingJob.PRIORITY_NORMAL)
        input_file_id = data.get('input_file_id')
        
        if input_file_id:
            try:
                input_file = GeoFile.objects.get(id=input_file_id)
                # Files > 500 MB should use normal priority
                if input_file.size_bytes > 500 * 1024 * 1024:
                    priority = GeoProcessingJob.PRIORITY_NORMAL
            except GeoFile.DoesNotExist:
                pass
        
        # Create job
        job = GeoProcessingJob.objects.create(
            org_id=data.get('org_id'),
            workflow_code=data['workflow_code'],
            priority=priority,
            idempotency_key=idempotency_key,
            input_file_id=input_file_id,
            parameters=data['parameters'],
            requested_by=request.user if request.user.is_authenticated else None,
        )
        
        # Trigger Celery task (FR-JOB-001)
        task = execute_workflow_job.delay(str(job.id))
        
        return Response({
            'id': str(job.id),
            'status': job.status,
            'workflow_code': job.workflow_code,
            'celery_task_id': task.id,
            'created_at': job.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)
