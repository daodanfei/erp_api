from rest_framework import serializers

from core_apps.policies.registry import get_policy

from business_apps.inventory.features import FIELD_PURCHASE_ORDER_ITEM_WAREHOUSE
from .models import (
    PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem,
    PurchaseApprovalLog, PurchaseChangeLog, PurchaseAttachment
)


class PurchaseWarehouseFieldRuleSerializerMixin:
    warehouse_field_rule_key = FIELD_PURCHASE_ORDER_ITEM_WAREHOUSE

    def _get_warehouse_field_rule(self):
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return {"visible": True, "required": False, "readonly": False}
        policy = get_policy("inventory", user=request.user)
        return policy.get_field_rule(self.warehouse_field_rule_key)

    def get_fields(self):
        fields = super().get_fields()
        if not self._get_warehouse_field_rule().get("visible", True):
            fields.pop("warehouse", None)
            fields.pop("warehouse_name", None)
        return fields


class PurchaseOrderItemSerializer(PurchaseWarehouseFieldRuleSerializerMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    warehouse_field_rule = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        fields = '__all__'

    def get_warehouse_field_rule(self, obj):
        return self._get_warehouse_field_rule()


class PurchaseReceiptItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    purchase_order_item_id = serializers.IntegerField(source='purchase_order_item.id', read_only=True)

    class Meta:
        model = PurchaseReceiptItem
        fields = '__all__'


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    executed_by_name = serializers.CharField(source='executed_by.username', read_only=True)
    purchase_order_no = serializers.CharField(source='purchase_order.purchase_order_no', read_only=True)

    class Meta:
        model = PurchaseReceipt
        fields = '__all__'


class PurchaseApprovalLogSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = PurchaseApprovalLog
        fields = '__all__'


class PurchaseChangeLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = PurchaseChangeLog
        fields = '__all__'


class PurchaseAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.username', read_only=True)

    class Meta:
        model = PurchaseAttachment
        fields = '__all__'


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    receipts = PurchaseReceiptSerializer(many=True, read_only=True)
    approval_logs = PurchaseApprovalLogSerializer(many=True, read_only=True)
    change_logs = PurchaseChangeLogSerializer(many=True, read_only=True)
    attachments = PurchaseAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = '__all__'
        read_only_fields = ('purchase_order_no', 'status', 'total_quantity', 'total_amount', 'created_by', 'dept')


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    """列表页用的轻量序列化器，不嵌套明细"""
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'purchase_order_no', 'supplier', 'supplier_name',
            'supplier_name_snapshot', 'supplier_code_snapshot',
            'status', 'order_date', 'expected_arrival_date',
            'total_quantity', 'total_amount', 'remark',
            'dept', 'created_by', 'created_by_name', 'closed_at', 'created_at', 'updated_at'
        ]


class PurchaseReceiptListSerializer(serializers.ModelSerializer):
    """入库单列表页用的轻量序列化器"""
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    executed_by_name = serializers.CharField(source='executed_by.username', read_only=True)
    purchase_order_no = serializers.CharField(source='purchase_order.purchase_order_no', read_only=True)

    class Meta:
        model = PurchaseReceipt
        fields = [
            'id', 'receipt_no', 'purchase_order', 'purchase_order_no',
            'warehouse', 'warehouse_name', 'status', 'remark',
            'received_at', 'cancelled_at', 'created_by', 'created_by_name',
            'executed_by', 'executed_by_name', 'created_at'
        ]
