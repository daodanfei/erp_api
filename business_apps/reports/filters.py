from django_filters import rest_framework as filters
from .models import ReportExportTask


class ReportExportTaskFilter(filters.FilterSet):
    report_type = filters.CharFilter(field_name='report_type')
    status = filters.CharFilter(field_name='status')

    class Meta:
        model = ReportExportTask
        fields = ['report_type', 'status']
