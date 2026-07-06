from rest_framework import serializers
from .models import ReportExportTask, ReportSnapshot


class ReportExportTaskSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ReportExportTask
        fields = '__all__'
        read_only_fields = ('status', 'file_url', 'file_name', 'error_message', 'created_by', 'completed_at')


class ReportSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportSnapshot
        fields = '__all__'
