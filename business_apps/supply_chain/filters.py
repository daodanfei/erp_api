import django_filters
from django.db import models as db_models
from .models import OutboundOrder, TransferOrder, SalesReturnOrder, PurchaseReturnOrder, InventoryAlert


class OutboundOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = OutboundOrder
        fields = ['status', 'warehouse']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            db_models.Q(outbound_no__icontains=value) |
            db_models.Q(sales_order__order_no__icontains=value)
        )


class TransferOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = TransferOrder
        fields = ['status', 'from_warehouse', 'to_warehouse']

    def filter_search(self, queryset, name, value):
        return queryset.filter(transfer_no__icontains=value)


class SalesReturnOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = SalesReturnOrder
        fields = ['status', 'warehouse', 'customer', 'sales_order']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            db_models.Q(return_no__icontains=value) |
            db_models.Q(customer_name_snapshot__icontains=value)
        )


class PurchaseReturnOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = PurchaseReturnOrder
        fields = ['status', 'warehouse', 'supplier', 'purchase_order']

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            db_models.Q(return_no__icontains=value) |
            db_models.Q(supplier_name_snapshot__icontains=value)
        )


class InventoryAlertFilter(django_filters.FilterSet):
    alert_type = django_filters.CharFilter(field_name='alert_type', lookup_expr='iexact')
    is_resolved = django_filters.BooleanFilter(field_name='is_resolved')

    class Meta:
        model = InventoryAlert
        fields = ['alert_type', 'is_resolved', 'warehouse']
