from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from core_apps.common.permissions import ERPActionPermission
from core_apps.common.viewsets import (
    ModuleAwareModelViewSet,
    build_erp_tenant_save_kwargs,
    validate_erp_related_tenant_scope,
)
from core_apps.erp_auth.compat import build_erp_user_fk_kwargs
from core_apps.policies.registry import get_policy
from .models import CashAccount, FinanceExportTask
from .serializers import CashAccountSerializer, CashAccountTransactionSerializer, FinanceExportTaskSerializer
from .services import FinanceStatsService, ReconciliationService

class FinanceViewSet(viewsets.ViewSet):
    module_key = "finance"
    permission_classes = [ERPActionPermission]
    permission_map = {
        'dashboard': 'finance:dashboard:view',
        'aging': 'finance:aging:view',
        'customer_reconciliation': 'finance:reconciliation:customer:view',
        'supplier_reconciliation': 'finance:reconciliation:supplier:view',
    }

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        policy = get_policy("finance", user=request.user)
        kpis = FinanceStatsService.get_dashboard_kpis(request.user)
        trend = FinanceStatsService.get_cash_flow_trend(request.user) if policy.cash_flow_analysis_enabled() else []
        return Response({
            'kpis': kpis,
            'trend': trend
        })

    @action(detail=False, methods=['get'])
    def aging(self, request):
        aging_type = request.query_params.get('type', 'AR')
        summary = FinanceStatsService.get_aging_summary(request.user, aging_type)
        return Response(summary)

    @action(detail=False, methods=['get'], url_path=r'reconciliation/customer/(?P<customer_id>\d+)')
    def customer_reconciliation(self, request, customer_id=None):
        policy = get_policy("finance", user=request.user)
        ar_policy = get_policy("ar_receivable", user=request.user)
        if not policy.reconciliation_enabled() or not ar_policy.customer_reconciliation_enabled():
            return Response({"detail": "当前配置未启用对账中心"}, status=status.HTTP_400_BAD_REQUEST)
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if not all([start_date, end_date]):
            return Response({"detail": "请选择对账周期"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            statement = ReconciliationService.get_customer_statement(request.user, customer_id, start_date, end_date)
            return Response(statement)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path=r'reconciliation/supplier/(?P<supplier_id>\d+)')
    def supplier_reconciliation(self, request, supplier_id=None):
        policy = get_policy("finance", user=request.user)
        ap_policy = get_policy("ap_payable", user=request.user)
        if not policy.reconciliation_enabled() or not ap_policy.supplier_reconciliation_enabled():
            return Response({"detail": "当前配置未启用对账中心"}, status=status.HTTP_400_BAD_REQUEST)
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if not all([start_date, end_date]):
            return Response({"detail": "请选择对账周期"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            statement = ReconciliationService.get_supplier_statement(request.user, supplier_id, start_date, end_date)
            return Response(statement)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class CashAccountViewSet(ModuleAwareModelViewSet):
    module_key = "finance"
    queryset = CashAccount.objects.all()
    serializer_class = CashAccountSerializer
    permission_classes = [ERPActionPermission]
    permission_map = {
        'list': 'finance:cash:view',
        'retrieve': 'finance:cash:view',
        'create': 'finance:cash:create',
        'update': 'finance:cash:update',
        'partial_update': 'finance:cash:update',
        'destroy': 'finance:cash:update',
        'transactions': 'finance:cash:view',
    }

    def perform_create(self, serializer):
        policy = get_policy("finance", user=self.request.user)
        if not policy.multi_cash_account_enabled() and self.get_queryset().filter(status=True).exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置仅允许单资金账户")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save(**build_erp_tenant_save_kwargs(self.queryset.model, user=self.request.user))

    def perform_update(self, serializer):
        policy = get_policy("finance", user=self.request.user)
        instance = serializer.instance
        if (
            not policy.opening_balance_editable()
            and instance.transactions.exists()
            and (
                "opening_balance_date" in serializer.validated_data
                or "current_balance" in serializer.validated_data
            )
        ):
            from rest_framework.exceptions import ValidationError
            raise ValidationError("当前配置不允许修改已启用账户的期初信息")
        validate_erp_related_tenant_scope(self.queryset.model, validated_data=serializer.validated_data, user=self.request.user)
        serializer.save()

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        account = self.get_object()
        serializer = CashAccountTransactionSerializer(account.transactions.all(), many=True)
        return Response(serializer.data)

class ExportTaskViewSet(ModuleAwareModelViewSet):
    module_key = "finance"
    queryset = FinanceExportTask.objects.all()
    serializer_class = FinanceExportTaskSerializer
    permission_classes = [ERPActionPermission]
    permission_map = {
        'list': 'finance:export_task:view',
        'retrieve': 'finance:export_task:view',
        'create': 'finance:export_task:create',
        'update': 'finance:export_task:update',
        'partial_update': 'finance:export_task:update',
        'destroy': 'finance:export_task:delete',
    }

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            **build_erp_user_fk_kwargs(
                FinanceExportTask,
                user=self.request.user,
                field_names=("created_by",),
            ),
        )
