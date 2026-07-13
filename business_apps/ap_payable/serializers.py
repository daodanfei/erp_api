from rest_framework import serializers
from .models import APAccount, APPayment, APAllocation, APOperationLog, SupplierRefund
from core_apps.common.authz import has_erp_role_permission
from core_apps.erp_auth.compat import get_erp_user_id


PAYMENT_APPROVE_PERMISSION_CODE = 'ap:payment:approve'
PAYMENT_EXECUTE_PERMISSION_CODE = 'ap:payment:execute'
REFUND_APPROVE_PERMISSION_CODE = 'ap:refund:approve'
REFUND_EXECUTE_PERMISSION_CODE = 'ap:refund:execute'

class APAllocationSerializer(serializers.ModelSerializer):
    ap_no = serializers.CharField(source='ap_account.ap_no', read_only=True)
    payment_no = serializers.CharField(source='payment.payment_no', read_only=True)
    class Meta:
        model = APAllocation
        fields = '__all__'

class APOperationLogSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    class Meta:
        model = APOperationLog
        fields = '__all__'

class APAccountSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    purchase_receipt_no = serializers.CharField(source='purchase_receipt.receipt_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    balance_amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    allocations = APAllocationSerializer(many=True, read_only=True)
    
    class Meta:
        model = APAccount
        fields = '__all__'
        read_only_fields = ('ap_no', 'status', 'paid_amount', 'created_by')

class APPaymentSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    unallocated_amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    allocations = APAllocationSerializer(many=True, read_only=True)
    can_execute = serializers.SerializerMethodField()
    
    class Meta:
        model = APPayment
        fields = '__all__'
        read_only_fields = ('payment_no', 'status', 'allocated_amount', 'created_by', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'executed_at')

    def get_can_execute(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.executed_at:
            return False
        if obj.status != 'APPROVED':
            return False
        return has_erp_role_permission(user, PAYMENT_EXECUTE_PERMISSION_CODE)


class SupplierRefundSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.supplier_name', read_only=True)
    credit_note_no = serializers.CharField(source='credit_note.credit_note_no', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)
    can_submit = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    can_execute = serializers.SerializerMethodField()

    class Meta:
        model = SupplierRefund
        fields = '__all__'
        read_only_fields = ('refund_no', 'status', 'created_by', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at', 'executed_at')

    def get_can_submit(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if obj.status != 'DRAFT':
            return False
        return has_erp_role_permission(user, 'ap:refund:submit')

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
