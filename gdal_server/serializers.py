from rest_framework import serializers


class ConvertRequestSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    input_path = serializers.CharField()
    input_driver = serializers.CharField()
    input_driver_ext = serializers.CharField()
    conversion_driver = serializers.CharField()
    conversion_driver_ext = serializers.CharField()
    callback_url = serializers.CharField(required=False, allow_null=True)
    conversion_kwargs = serializers.DictField(required=False, default={})
