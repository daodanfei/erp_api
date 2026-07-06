from rest_framework import serializers
from core_apps.policies.registry import get_policy

from business_apps.inventory.features import FIELD_SALES_ORDER_ITEM_WAREHOUSE
from .models import SalesOrder, SalesOrderItem, Shipment, ShipmentItem, OrderApprovalLog, OrderChangeLog, OrderAttachment, SalesExecutionLog
from business_apps.supply_chain.serializers import OutboundOrderListSerializer


class SalesWarehouseFieldRuleSerializerMixin:
    warehouse_field_rule_key = FIELD_SALES_ORDER_ITEM_WAREHOUSE

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


class SalesOrderItemSerializer(SalesWarehouseFieldRuleSerializerMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_code = serializers.CharField(source='product.product_code', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.warehouse_name', read_only=True)
    warehouse_field_rule = serializers.SerializerMethodField()
    
    class Meta:
        model = SalesOrderItem
        fields = '__all__'

    def get_warehouse_field_rule(self, obj):
        return self._get_warehouse_field_rule()

class OrderApprovalLogSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    class Meta:
        model = OrderApprovalLog
        fields = '__all__'

class ShipmentItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    class Meta:
        model = ShipmentItem
        fields = '__all__'

class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    class Meta:
        model = Shipment
        fields = '__all__'

class OrderAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAttachment
        fields = '__all__'

class SalesExecutionLogSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = SalesExecutionLog
        fields = '__all__'

class SalesOrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    items = SalesOrderItemSerializer(many=True, read_only=True)
    approval_logs = OrderApprovalLogSerializer(many=True, read_only=True)
    shipments = ShipmentSerializer(many=True, read_only=True)
    outbound_orders = OutboundOrderListSerializer(many=True, read_only=True)
    attachments = OrderAttachmentSerializer(many=True, read_only=True)
    execution_logs = SalesExecutionLogSerializer(many=True, read_only=True)
    
    class Meta:
        model = SalesOrder
        fields = '__all__'
        read_only_fields = ('order_no', 'status', 'total_quantity', 'total_amount', 'created_by')
