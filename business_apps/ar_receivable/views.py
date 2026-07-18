from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from core_apps.common.viewsets import BaseBusinessViewSet, ModuleAwareReadOnlyViewSet
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.erp_auth.compat import as_erp_user
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from .models import CustomerRefund, Receivable, Receipt, WriteOff
from .serializers import CustomerRefundSerializer, ReceivableSerializer, ReceiptSerializer, WriteOffSerializer
from .services import ARService
from business_apps.crm.models import Customer
from business_apps.sales.models import SalesOrder
from business_apps.finance.models import CashAccount
from core_apps.policies.registry import get_policy


RECEIPT_APPROVE_PERMISSION_CODE = 'ar:receipt:approve'
RECEIPT_EXECUTE_PERMISSION_CODE = 'ar:receipt:execute'
RECEIPT_WRITE_OFF_PERMISSION_CODE = 'ar:receipt:write_off'

class ReceivableViewSet(BaseBusinessViewSet):
    module_key = "ar_receivable"
    queryset = Receivable.objects.filter(is_deleted=False)
    serializer_class = ReceivableSerializer
    filterset_fields = ['customer', 'status']
    
    permission_map = {
        'list': 'ar:receivable:view',
        'retrieve': 'ar:receivable:view',
        'update': 'ar:receivable:update',
        'generate': 'ar:receivable:generate',
        'aging_analysis': 'ar:aging:view',
    }

    @action(detail=False, methods=['post'])
    def generate(self, request):
        order_id = request.data.get('sales_order')
        if not order_id:
            return Response({"detail": "缺少销售订单ID"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            order = self.get_scoped_related_object(SalesOrder.objects.all(), id=order_id)
            receivable = ARService.generate_ar_from_order(order, request.user)
            serializer = self.get_serializer(receivable)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
    @action(detail=False, methods=['get'])
    def aging_analysis(self, request):
        policy = get_policy("ar_receivable", user=request.user)
        if not policy.overdue_tracking_enabled():
            return Response({"detail": "当前配置未启用应收逾期跟踪"}, status=status.HTTP_400_BAD_REQUEST)
        customer_id = request.query_params.get('customer')
        analysis = ARService.get_aging_analysis(request.user, customer_id)
        return Response(analysis)

class ReceiptViewSet(BaseBusinessViewSet):
    module_key = "ar_receivable"
    queryset = Receipt.objects.filter(is_deleted=False)
    serializer_class = ReceiptSerializer
    filterset_fields = ['customer', 'status', 'payment_method']
    
    permission_map = {
        'list': 'ar:receipt:view',
        'retrieve': 'ar:receipt:view',
        'create': 'ar:receipt:create',
        'update': 'ar:receipt:update',
        'destroy': 'ar:receipt:delete',
        'approve': 'ar:receipt:approve',
        'execute': 'ar:receipt:execute',
        'write_off': 'ar:receipt:write_off',
    }

    def get_queryset(self):
        queryset = self.get_tenant_scoped_queryset()
        if self.get_data_permission_type(queryset) != "BUSINESS":
            return self.apply_data_permission_scope(queryset)
        user = self.request.user
        scope_q = get_data_scope_filter(user, dept_field=self.dept_field, user_field=self.user_field)
        if not scope_q.children:
            return queryset.distinct()
        visible_q = scope_q
        erp_user = as_erp_user(user)

        # Approval workbench must be able to access drafts created by other users,
        # otherwise "different person reviews" cannot be executed under SELF scope.
        if getattr(self, 'action', None) in ['list', 'retrieve', 'approve', 'execute'] and user.roles.filter(
            permissions__code=RECEIPT_APPROVE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            pending_q = Q(status='DRAFT')
            if erp_user is not None:
                pending_q &= ~Q(created_by=erp_user)
            visible_q |= pending_q

        if getattr(self, 'action', None) in ['list', 'retrieve', 'execute'] and user.roles.filter(
            permissions__code=RECEIPT_EXECUTE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            visible_q |= Q(status__in=['UNWRITTEN', 'PARTIAL_WRITTEN', 'WRITTEN'], executed_at__isnull=True)

        # After approval, receipts move to UNWRITTEN/PARTIAL_WRITTEN/WRITTEN and must
        # stay visible to users who are responsible for write-off work.
        if getattr(self, 'action', None) in ['list', 'retrieve', 'write_off'] and user.roles.filter(
            permissions__code=RECEIPT_WRITE_OFF_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            visible_q |= Q(status__in=['UNWRITTEN', 'PARTIAL_WRITTEN', 'WRITTEN'])

        return queryset.filter(visible_q).distinct()

    def create(self, request, *args, **kwargs):
        try:
            customer = self.get_tenant_scoped_related_object(Customer.objects.all(), id=request.data.get('customer'))
            amount = float(request.data.get('amount'))
            receipt_date = request.data.get('receipt_date')
            payment_method = request.data.get('payment_method')
            
            receipt = ARService.create_receipt(
                customer=customer,
                amount=amount,
                receipt_date=receipt_date,
                payment_method=payment_method,
                cash_account=(
                    self.get_tenant_scoped_related_object(CashAccount.objects.all(), id=request.data.get('cash_account'))
                    if request.data.get('cash_account') else None
                ),
                operator=request.user,
                reference_no=request.data.get('reference_no'),
                remark=request.data.get('remark')
            )
            serializer = self.get_serializer(receipt)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        receipt = self.get_object()
        try:
            ARService.approve_receipt(receipt, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        receipt = self.get_object()
        try:
            ARService.execute_receipt(receipt, request.user)
            return Response({'status': 'executed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def write_off(self, request, pk=None):
        receipt_id = pk
        receivable_id = request.data.get('receivable')
        amount = float(request.data.get('amount', 0))
        
        try:
            receipt = self.get_scoped_related_object(Receipt.objects.all(), id=receipt_id)
            receivable = self.get_scoped_related_object(Receivable.objects.all(), id=receivable_id)
            receivable, receipt = ARService.write_off(receivable.id, receipt.id, amount, request.user)
            return Response({"status": "success", "detail": "核销成功"})
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class WriteOffViewSet(ModuleAwareReadOnlyViewSet):
    module_key = "ar_receivable"
    queryset = WriteOff.objects.all()
    serializer_class = WriteOffSerializer
    filterset_fields = ['receivable', 'receipt']

    def get_queryset(self):
        policy = get_policy("ar_receivable", user=self.request.user)
        if not policy.writeoff_enabled():
            return WriteOff.objects.none()
        return super().get_queryset()


class CustomerRefundViewSet(BaseBusinessViewSet):
    module_key = "ar_receivable"
    queryset = CustomerRefund.objects.filter(is_deleted=False)
    serializer_class = CustomerRefundSerializer
    filterset_fields = ['customer', 'receivable', 'status', 'payment_method']

    permission_map = {
        'list': 'ar:refund:view',
        'retrieve': 'ar:refund:view',
        'create': 'ar:refund:create',
        'update': 'ar:refund:update',
        'destroy': 'ar:refund:delete',
        'submit': 'ar:refund:submit',
        'approve': 'ar:refund:approve',
        'execute': 'ar:refund:execute',
    }

    def get_queryset(self):
        queryset = self.get_tenant_scoped_queryset()
        if self.get_data_permission_type(queryset) != "BUSINESS":
            return self.apply_data_permission_scope(queryset)
        user = self.request.user
        scope_q = get_data_scope_filter(user, dept_field=self.dept_field, user_field=self.user_field)
        if not scope_q.children:
            return queryset.distinct()

        visible_q = scope_q
        erp_user = as_erp_user(user)
        if getattr(self, 'action', None) in ['list', 'retrieve', 'approve'] and user.roles.filter(
            permissions__code='ar:refund:approve',
            permissions__status=True,
            status=True,
        ).exists():
            pending_q = Q(status='PENDING_APPROVAL')
            if erp_user is not None:
                pending_q &= ~Q(created_by=erp_user) & ~Q(submitted_by=erp_user)
            visible_q |= pending_q

        if getattr(self, 'action', None) in ['list', 'retrieve', 'execute'] and user.roles.filter(
            permissions__code='ar:refund:execute',
            permissions__status=True,
            status=True,
        ).exists():
            visible_q |= Q(status='APPROVED', executed_at__isnull=True)

        return queryset.filter(visible_q).distinct()

    def create(self, request, *args, **kwargs):
        try:
            customer = self.get_scoped_related_object(Customer.objects.filter(is_deleted=False), id=request.data.get('customer'))
            receivable = self.get_scoped_related_object(Receivable.objects.all(), id=request.data.get('receivable'))
            refund = ARService.create_customer_refund(
                customer=customer,
                receivable=receivable,
                refund_date=request.data.get('refund_date'),
                payment_method=request.data.get('payment_method', 'BANK_TRANSFER'),
                cash_account=(
                    self.get_scoped_related_object(CashAccount.objects.all(), id=request.data.get('cash_account'))
                    if request.data.get('cash_account') else None
                ),
                operator=request.user,
                reference_no=request.data.get('reference_no'),
                remark=request.data.get('remark'),
            )
            serializer = self.get_serializer(refund)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ObjectDoesNotExist:
            return Response({"detail": "关联数据不存在或不属于当前租户"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        refund = self.get_object()
        try:
            ARService.submit_customer_refund(refund, request.user)
            return Response({'status': 'pending_approval'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        refund = self.get_object()
        try:
            ARService.approve_customer_refund(refund, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        refund = self.get_object()
        try:
            ARService.execute_customer_refund(
                refund,
                request.user,
                payment_method=request.data.get('payment_method'),
                cash_account=(
                    self.get_scoped_related_object(CashAccount.objects.all(), id=request.data.get('cash_account'))
                    if request.data.get('cash_account') else None
                ),
                bank_account=request.data.get('bank_account'),
                reference_no=request.data.get('reference_no'),
                remark=request.data.get('remark'),
            )
            return Response({'status': 'executed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
