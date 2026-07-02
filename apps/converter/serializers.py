from rest_framework import serializers
from .models import (
    GeoFile,
    GeoFileLayer,
    Workflow,
    GeoProcessingJob,
    GeoProcessingJobLog,
    DispatchedLayer,
    DestinationCredential,
    AuditLog
)

class GeoFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFile
        fields = '__all__'


class GeoFileLayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFileLayer
        fields = '__all__'


class WorkflowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = '__all__'


class GeoProcessingJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoProcessingJob
        fields = '__all__'


class GeoProcessingJobLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoProcessingJobLog
        fields = '__all__'


class DispatchedLayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchedLayer
        fields = '__all__'


class DestinationCredentialSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationCredential
        # Exclude the sensitive encrypted_secret binary field to prevent serialization issues
        fields = ['id', 'org_id', 'name', 'target_type', 'metadata', 'created_at', 'updated_at']


class AuditLogSerializer(serializers.ModelSerializer):
    ip_address = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = AuditLog
        fields = '__all__'
