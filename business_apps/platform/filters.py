from django_filters import rest_framework as filters
from .models import File, DictType, CodeRule


class FileFilter(filters.FilterSet):
    module = filters.CharFilter(field_name='module')
    business_type = filters.CharFilter(field_name='business_type')
    business_id = filters.NumberFilter(field_name='business_id')
    file_name = filters.CharFilter(field_name='file_name', lookup_expr='icontains')
    storage_type = filters.CharFilter(field_name='storage_type')

    class Meta:
        model = File
        fields = ['module', 'business_type', 'business_id', 'storage_type']


class DictTypeFilter(filters.FilterSet):
    dict_code = filters.CharFilter(field_name='dict_code', lookup_expr='icontains')
    dict_name = filters.CharFilter(field_name='dict_name', lookup_expr='icontains')
    status = filters.CharFilter(field_name='status')

    class Meta:
        model = DictType
        fields = ['dict_code', 'dict_name', 'status']


class CodeRuleFilter(filters.FilterSet):
    rule_code = filters.CharFilter(field_name='rule_code', lookup_expr='icontains')
    rule_name = filters.CharFilter(field_name='rule_name', lookup_expr='icontains')
    status = filters.CharFilter(field_name='status')

    class Meta:
        model = CodeRule
        fields = ['rule_code', 'rule_name', 'status']
