import django_filters
from django.db import models as db_models

from .models import Receivable, Receipt, WriteOff


class ReceivableFilter(django_filters.FilterSet):
    customer = django_filters.NumberFilter(field_name='customer')
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    due_date_from = django_filters.DateFilter(field_name='due_date', lookup_expr='gte')
    due_date_to = django_filters.DateFilter(field_name='due_date', lookup_expr='lte')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Receivable
        fields = ['customer', 'status', 'due_date_from', 'due_date_to']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            db_models.Q(receivable_no__icontains=value) |
            db_models.Q(customer__customer_name__icontains=value) |
            db_models.Q(sales_order__order_no__icontains=value)
        )


class ReceiptFilter(django_filters.FilterSet):
    customer = django_filters.NumberFilter(field_name='customer')
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    payment_method = django_filters.CharFilter(field_name='payment_method', lookup_expr='iexact')
    receipt_date_from = django_filters.DateFilter(field_name='receipt_date', lookup_expr='gte')
    receipt_date_to = django_filters.DateFilter(field_name='receipt_date', lookup_expr='lte')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Receipt
        fields = ['customer', 'status', 'payment_method', 'receipt_date_from', 'receipt_date_to']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            db_models.Q(receipt_no__icontains=value) |
            db_models.Q(customer__customer_name__icontains=value) |
            db_models.Q(reference_no__icontains=value)
        )


class WriteOffFilter(django_filters.FilterSet):
    receivable = django_filters.NumberFilter(field_name='receivable')
    receipt = django_filters.NumberFilter(field_name='receipt')
    customer = django_filters.NumberFilter(field_name='receivable__customer')
    write_off_date_from = django_filters.DateFilter(field_name='write_off_date', lookup_expr='gte')
    write_off_date_to = django_filters.DateFilter(field_name='write_off_date', lookup_expr='lte')

    class Meta:
        model = WriteOff
        fields = ['receivable', 'receipt', 'customer', 'write_off_date_from', 'write_off_date_to']
