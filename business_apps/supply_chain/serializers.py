from rest_framework import serializers
from business_apps.inventory.serializers import ActiveWarehouseValidationMixin
from .models import (
    OutboundOrder, OutboundOrderItem,
    TransferOrder, TransferOrderItem,
    SalesReturnOrder, SalesReturnOrderItem,
    PurchaseReturnOrder, PurchaseReturnOrderItem,
    InventoryAlert,
)


# ==================== 销售出库 ====================

class OutboundOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    sales_order_item_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = OutboundOrderItem
        fields = '__all__'


class OutboundOrderSerializer(ActiveWarehouseValidationMixin, serializers.ModelSerializer):
    items = OutboundOrderItemSerializer(many=True, read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    sales_order_no = serializers.CharField(source='sales_order.order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = OutboundOrder
        fields = '__all__'
        read_only_fields = ('outbound_no', 'status', 'created_by', 'dept', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'completed_at')


class OutboundOrderListSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    sales_order_no = serializers.CharField(source='sales_order.order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = OutboundOrder
        fields = ['id', 'outbound_no', 'sales_order', 'sales_order_no', 'warehouse', 'warehouse_name', 'status', 'remark', 'created_by', 'created_by_name', 'submitted_by', 'submitted_by_name', 'approved_by', 'approved_by_name', 'created_at', 'completed_at']


# ==================== 仓库调拨 ====================

class TransferOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)

    class Meta:
        model = TransferOrderItem
        fields = '__all__'


class TransferOrderSerializer(serializers.ModelSerializer):
    items = TransferOrderItemSerializer(many=True, read_only=True)
    from_warehouse_name = serializers.CharField(source='from_warehouse.warehouse_name', read_only=True)
    to_warehouse_name = serializers.CharField(source='to_warehouse.warehouse_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    outbound_confirmed_by_name = serializers.CharField(source='outbound_confirmed_by.username', read_only=True)
    inbound_confirmed_by_name = serializers.CharField(source='inbound_confirmed_by.username', read_only=True)

    class Meta:
        model = TransferOrder
        fields = '__all__'
        read_only_fields = ('transfer_no', 'status', 'created_by', 'dept', 'completed_at', 'cancelled_at', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'outbound_confirmed_by', 'outbound_confirmed_at', 'inbound_confirmed_by', 'inbound_confirmed_at')

    def validate_from_warehouse(self, value):
        if value is None:
            return value
        if value.status is False:
            raise serializers.ValidationError("禁用仓库不能用于业务")
        return value

    def validate_to_warehouse(self, value):
        if value is None:
            return value
        if value.status is False:
            raise serializers.ValidationError("禁用仓库不能用于业务")
        return value


class TransferOrderListSerializer(serializers.ModelSerializer):
    from_warehouse_name = serializers.CharField(source='from_warehouse.warehouse_name', read_only=True)
    to_warehouse_name = serializers.CharField(source='to_warehouse.warehouse_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = TransferOrder
        fields = ['id', 'transfer_no', 'from_warehouse', 'from_warehouse_name', 'to_warehouse', 'to_warehouse_name', 'status', 'remark', 'created_by', 'created_by_name', 'submitted_by', 'submitted_by_name', 'approved_by', 'approved_by_name', 'created_at', 'completed_at']


# ==================== 销售退货 ====================

class SalesReturnOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)

    class Meta:
        model = SalesReturnOrderItem
        fields = '__all__'


class SalesReturnOrderSerializer(ActiveWarehouseValidationMixin, serializers.ModelSerializer):
    items = SalesReturnOrderItemSerializer(many=True, read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    sales_order_no = serializers.CharField(source='sales_order.order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = SalesReturnOrder
        fields = '__all__'
        read_only_fields = ('return_no', 'status', 'finance_status', 'created_by', 'dept', 'completed_at')


class SalesReturnOrderListSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    customer_name_snapshot = serializers.CharField(read_only=True)
    sales_order_no = serializers.CharField(source='sales_order.order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = SalesReturnOrder
        fields = ['id', 'return_no', 'customer', 'customer_name_snapshot', 'sales_order', 'sales_order_no', 'warehouse', 'warehouse_name', 'status', 'finance_status', 'reason', 'created_by', 'created_by_name', 'created_at', 'completed_at']


# ==================== 采购退货 ====================

class PurchaseReturnOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)

    class Meta:
        model = PurchaseReturnOrderItem
        fields = '__all__'


class PurchaseReturnOrderSerializer(ActiveWarehouseValidationMixin, serializers.ModelSerializer):
    items = PurchaseReturnOrderItemSerializer(many=True, read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    purchase_order_no = serializers.CharField(source='purchase_order.purchase_order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = PurchaseReturnOrder
        fields = '__all__'
        read_only_fields = ('return_no', 'status', 'finance_status', 'created_by', 'dept', 'completed_at')


class PurchaseReturnOrderListSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    supplier_name_snapshot = serializers.CharField(read_only=True)
    purchase_order_no = serializers.CharField(source='purchase_order.purchase_order_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = PurchaseReturnOrder
        fields = ['id', 'return_no', 'supplier', 'supplier_name_snapshot', 'purchase_order', 'purchase_order_no', 'warehouse', 'warehouse_name', 'status', 'finance_status', 'reason', 'created_by', 'created_by_name', 'created_at', 'completed_at']


# ==================== 库存预警 ====================

class InventoryAlertSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    resolved_by_name = serializers.CharField(source='resolved_by.username', read_only=True)

    class Meta:
        model = InventoryAlert
        fields = '__all__'
