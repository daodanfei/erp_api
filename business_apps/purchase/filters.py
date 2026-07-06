import django_filters
from django.db import models
from .models import PurchaseOrder, PurchaseReceipt


class PurchaseOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    supplier = django_filters.NumberFilter(field_name='supplier')
    search = django_filters.CharFilter(method='filter_search')
    start_date = django_filters.DateFilter(field_name='order_date', lookup_expr='gte')
    end_date = django_filters.DateFilter(field_name='order_date', lookup_expr='lte')

    class Meta:
        model = PurchaseOrder
        fields = ['status', 'supplier']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            models.Q(purchase_order_no__icontains=value) |
            models.Q(supplier_name_snapshot__icontains=value)
        )


class PurchaseReceiptFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    purchase_order = django_filters.NumberFilter(field_name='purchase_order')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = PurchaseReceipt
        fields = ['status', 'purchase_order']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            models.Q(receipt_no__icontains=value) |
            models.Q(purchase_order__purchase_order_no__icontains=value)
        )
