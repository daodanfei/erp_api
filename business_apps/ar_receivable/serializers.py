from rest_framework import serializers
from .models import CustomerRefund, Receivable, Receipt, WriteOff
from core_apps.common.authz import has_erp_role_permission
from core_apps.erp_auth.compat import get_erp_user_id


RECEIPT_APPROVE_PERMISSION_CODE = 'ar:receipt:approve'
RECEIPT_EXECUTE_PERMISSION_CODE = 'ar:receipt:execute'
REFUND_APPROVE_PERMISSION_CODE = 'ar:refund:approve'
REFUND_EXECUTE_PERMISSION_CODE = 'ar:refund:execute'

class WriteOffSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    receivable_no = serializers.CharField(source='receivable.receivable_no', read_only=True)
    receipt_no = serializers.CharField(source='receipt.receipt_no', read_only=True)

    class Meta:
        model = WriteOff
        fields = '__all__'

class ReceivableSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    order_no = serializers.CharField(source='sales_order.order_no', read_only=True)
    outbound_no = serializers.CharField(source='outbound_order.outbound_no', read_only=True)
    source_type_label = serializers.CharField(source='get_source_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    write_offs = WriteOffSerializer(many=True, read_only=True)
    
    # Computed fields
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    overdue_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = Receivable
        fields = '__all__'
        read_only_fields = ('receivable_no', 'status', 'written_off_amount', 'created_by')

class ReceiptSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    write_offs = WriteOffSerializer(many=True, read_only=True)
    can_approve = serializers.SerializerMethodField()
    can_execute = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = '__all__'
        read_only_fields = ('receipt_no', 'status', 'unwritten_amount', 'created_by', 'approved_by', 'approved_at', 'executed_at')

    def get_can_approve(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != 'DRAFT':
            return False
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and obj.created_by_id == erp_user_id:
            return False
        return has_erp_role_permission(user, RECEIPT_APPROVE_PERMISSION_CODE)

    def get_can_execute(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.executed_at:
            return False
        if obj.status not in ['UNWRITTEN', 'PARTIAL_WRITTEN', 'WRITTEN']:
            return False
        return has_erp_role_permission(user, RECEIPT_EXECUTE_PERMISSION_CODE)


class CustomerRefundSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.customer_name', read_only=True)
    receivable_no = serializers.CharField(source='receivable.receivable_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    can_submit = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    can_execute = serializers.SerializerMethodField()

    class Meta:
        model = CustomerRefund
        fields = '__all__'
        read_only_fields = ('refund_no', 'status', 'created_by', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'executed_at')

    def get_can_submit(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != 'DRAFT':
            return False
        return has_erp_role_permission(user, 'ar:refund:submit')

    def get_can_approve(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != 'PENDING_APPROVAL':
            return False
        erp_user_id = get_erp_user_id(user)
        if erp_user_id is not None and (
            obj.created_by_id == erp_user_id or obj.submitted_by_id == erp_user_id
        ):
            return False
        return has_erp_role_permission(user, REFUND_APPROVE_PERMISSION_CODE)

    def get_can_execute(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.executed_at:
            return False
        if obj.status != 'APPROVED':
            return False
        return has_erp_role_permission(user, REFUND_EXECUTE_PERMISSION_CODE)
