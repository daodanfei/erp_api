from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from core_apps.common.viewsets import BaseBusinessViewSet
from core_apps.common.permissions import ERPActionPermission
from core_apps.common.utils.data_scope import get_data_scope_filter
from core_apps.erp_auth.compat import as_erp_user
from django.db.models import Q
from .models import APAccount, APPayment, APAllocation
from .serializers import APAccountSerializer, APPaymentSerializer, APAllocationSerializer
from .services import APService
from business_apps.supplier.models import Supplier
from business_apps.finance.models import CashAccount
from core_apps.policies.registry import get_policy


PAYMENT_APPROVE_PERMISSION_CODE = 'ap:payment:approve'
PAYMENT_EXECUTE_PERMISSION_CODE = 'ap:payment:execute'

class APAccountViewSet(BaseBusinessViewSet):
    module_key = "ap_payable"
    queryset = APAccount.objects.filter(is_deleted=False)
    serializer_class = APAccountSerializer
    filterset_fields = ['supplier', 'status', 'due_date']
    
    permission_map = {
        'list': 'ap:account:view',
        'retrieve': 'ap:account:view',
        'update': 'ap:account:update',
        'statistics': 'ap:account:view',
        'supplier_summary': 'ap:account:view',
        'aging': 'ap:account:view',
    }

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        return Response(APService.get_statistics(start_date, end_date))

    @action(detail=False, methods=['get'])
    def supplier_summary(self, request):
        summary = APService.get_supplier_summary()
        return Response(summary)

    @action(detail=False, methods=['get'])
    def aging(self, request):
        supplier_id = request.query_params.get('supplier')
        analysis = APService.get_aging_analysis(supplier_id)
        return Response(analysis)

class APPaymentViewSet(BaseBusinessViewSet):
    module_key = "ap_payable"
    queryset = APPayment.objects.all()
    serializer_class = APPaymentSerializer
    filterset_fields = ['supplier', 'status', 'payment_method']
    
    permission_map = {
        'list': 'ap:payment:view',
        'retrieve': 'ap:payment:view',
        'create': 'ap:payment:create',
        'update': 'ap:payment:update',
        'destroy': 'ap:payment:delete',
        'submit': 'ap:payment:submit',
        'approve': 'ap:payment:approve',
        'execute': 'ap:payment:execute',
        'cancel': 'ap:payment:cancel',
    }

    def get_queryset(self):
        queryset = self.queryset
        user = self.request.user
        scope_q = get_data_scope_filter(user, dept_field=self.dept_field, user_field=self.user_field)
        visible_q = scope_q
        erp_user = as_erp_user(user)

        if getattr(self, 'action', None) in ['list', 'retrieve', 'approve'] and user.roles.filter(
            permissions__code=PAYMENT_APPROVE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            pending_q = Q(status='PENDING_APPROVAL')
            if erp_user is not None:
                pending_q &= ~Q(created_by=erp_user)
            visible_q |= pending_q

        if getattr(self, 'action', None) in ['list', 'retrieve', 'execute'] and user.roles.filter(
            permissions__code=PAYMENT_EXECUTE_PERMISSION_CODE,
            permissions__status=True,
            status=True,
        ).exists():
            visible_q |= Q(status='APPROVED', executed_at__isnull=True)

        return queryset.filter(visible_q).distinct()

    def create(self, request, *args, **kwargs):
        try:
            supplier = Supplier.objects.get(id=request.data.get('supplier'))
            payment = APService.create_payment(
                supplier=supplier,
                amount=float(request.data.get('payment_amount')),
                payment_date=request.data.get('payment_date'),
                payment_method=request.data.get('payment_method'),
                cash_account=CashAccount.objects.get(id=request.data.get('cash_account')) if request.data.get('cash_account') else None,
                operator=request.user,
                bank_account=request.data.get('bank_account'),
                remark=request.data.get('remark')
            )
            serializer = self.get_serializer(payment)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        payment = self.get_object()
        try:
            APService.submit_payment(payment, request.user)
            return Response({'status': 'pending_approval'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        payment = self.get_object()
        try:
            APService.approve_payment(payment, request.user)
            return Response({'status': 'approved'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        payment = self.get_object()
        try:
            APService.execute_payment(payment, request.user)
            return Response({'status': 'executed'})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class APAllocationViewSet(viewsets.ModelViewSet):
    module_key = "ap_payable"
    queryset = APAllocation.objects.all()
    serializer_class = APAllocationSerializer
    permission_classes = [ERPActionPermission]
    permission_map = {
        'list': 'ap:allocation:view',
        'retrieve': 'ap:allocation:view',
        'create': 'ap:allocation:create',
        'update': 'ap:allocation:update',
        'partial_update': 'ap:allocation:update',
        'destroy': 'ap:allocation:delete',
    }

    def get_queryset(self):
        policy = get_policy("ap_payable", user=self.request.user)
        if not policy.allocation_enabled() or not policy.writeoff_enabled():
            return APAllocation.objects.none()
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        payment_id = request.data.get('payment')
        ap_accounts_data = request.data.get('allocations', []) # list of {ap_id, amount}
        
        try:
            payment = APPayment.objects.get(id=payment_id)
            APService.allocate_payment(payment, ap_accounts_data, request.user)
            return Response({"status": "success"})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
