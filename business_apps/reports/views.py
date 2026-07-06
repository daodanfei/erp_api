from datetime import datetime
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from core_apps.common.permissions import ERPActionPermission
from core_apps.policies.registry import get_policy
from .services import (
    DashboardService, SalesReportService, PurchaseReportService,
    InventoryReportService, CustomerReportService, SupplierReportService,
    ProductReportService, ExportService,
)
from .models import ReportExportTask
from .serializers import ReportExportTaskSerializer


def _parse_date(date_str):
    """解析日期字符串"""
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


class ReportFeatureAPIView(APIView):
    permission_classes = [IsAuthenticated, ERPActionPermission]
    module_key = "reports"
    feature_key = ""
    feature_error_message = "当前配置未启用报表功能"

    def initial(self, request, *args, **kwargs):
        response = super().initial(request, *args, **kwargs)
        policy = get_policy(self.module_key, user=request.user)
        if not policy.is_feature_enabled(self.feature_key, default=True):
            raise ValidationError({"detail": self.feature_error_message})
        return response


class DashboardView(ReportFeatureAPIView):
    feature_key = "dashboard"
    feature_error_message = "当前配置未启用经营驾驶舱"
    permission_map = {'get': 'reports:dashboard:view'}

    def get(self, request):
        days = int(request.query_params.get('days', 30))
        data = {
            'kpi': DashboardService.get_kpi(request.user),
            'sales_trend': DashboardService.get_sales_trend(request.user, days=days),
            'purchase_trend': DashboardService.get_purchase_trend(request.user, days=days),
            'inventory_overview': DashboardService.get_inventory_overview(request.user),
            'top10': DashboardService.get_top10(request.user),
        }
        return Response(data)


class SalesSummaryView(ReportFeatureAPIView):
    feature_key = "sales_analysis"
    feature_error_message = "当前配置未启用销售分析"
    permission_map = {'get': 'reports:sales:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = SalesReportService.get_summary(request.user, period, start_date, end_date)
        return Response(data)


class SalesTrendView(ReportFeatureAPIView):
    feature_key = "sales_analysis"
    feature_error_message = "当前配置未启用销售分析"
    permission_map = {'get': 'reports:sales:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        granularity = request.query_params.get('granularity', 'day')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = SalesReportService.get_trend(request.user, period, granularity, start_date, end_date)
        return Response(data)


class SalesProductRankingView(ReportFeatureAPIView):
    feature_key = "sales_analysis"
    feature_error_message = "当前配置未启用销售分析"
    permission_map = {'get': 'reports:sales:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = SalesReportService.get_product_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class SalesCustomerRankingView(ReportFeatureAPIView):
    feature_key = "sales_analysis"
    feature_error_message = "当前配置未启用销售分析"
    permission_map = {'get': 'reports:sales:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = SalesReportService.get_customer_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class PurchaseSummaryView(ReportFeatureAPIView):
    feature_key = "purchase_analysis"
    feature_error_message = "当前配置未启用采购分析"
    permission_map = {'get': 'reports:purchase:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = PurchaseReportService.get_summary(request.user, period, start_date, end_date)
        return Response(data)


class PurchaseTrendView(ReportFeatureAPIView):
    feature_key = "purchase_analysis"
    feature_error_message = "当前配置未启用采购分析"
    permission_map = {'get': 'reports:purchase:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        granularity = request.query_params.get('granularity', 'day')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = PurchaseReportService.get_trend(request.user, period, granularity, start_date, end_date)
        return Response(data)


class PurchaseSupplierRankingView(ReportFeatureAPIView):
    feature_key = "purchase_analysis"
    feature_error_message = "当前配置未启用采购分析"
    permission_map = {'get': 'reports:purchase:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = PurchaseReportService.get_supplier_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class PurchaseProductRankingView(ReportFeatureAPIView):
    feature_key = "purchase_analysis"
    feature_error_message = "当前配置未启用采购分析"
    permission_map = {'get': 'reports:purchase:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = PurchaseReportService.get_product_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class InventorySummaryView(ReportFeatureAPIView):
    feature_key = "inventory_analysis"
    feature_error_message = "当前配置未启用库存分析"
    permission_map = {'get': 'reports:inventory:view'}

    def get(self, request):
        data = InventoryReportService.get_summary(request.user)
        return Response(data)


class InventoryAgingView(ReportFeatureAPIView):
    feature_key = "inventory_analysis"
    feature_error_message = "当前配置未启用库存分析"
    permission_map = {'get': 'reports:inventory:view'}

    def get(self, request):
        data = InventoryReportService.get_aging(request.user)
        return Response(data)


class InventoryAlertsView(ReportFeatureAPIView):
    feature_key = "inventory_analysis"
    feature_error_message = "当前配置未启用库存分析"
    permission_map = {'get': 'reports:inventory:view'}

    def get(self, request):
        data = InventoryReportService.get_alerts(request.user)
        return Response(data)


class InventoryTransactionSummaryView(ReportFeatureAPIView):
    feature_key = "inventory_analysis"
    feature_error_message = "当前配置未启用库存分析"
    permission_map = {'get': 'reports:inventory:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = InventoryReportService.get_transaction_summary(request.user, period, start_date, end_date)
        return Response(data)


class CustomerStatsView(ReportFeatureAPIView):
    feature_key = "customer_analysis"
    feature_error_message = "当前配置未启用客户分析"
    permission_map = {'get': 'reports:customer:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = CustomerReportService.get_stats(request.user, period, start_date, end_date)
        return Response(data)


class CustomerRankingView(ReportFeatureAPIView):
    feature_key = "customer_analysis"
    feature_error_message = "当前配置未启用客户分析"
    permission_map = {'get': 'reports:customer:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = CustomerReportService.get_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class CustomerActivityView(ReportFeatureAPIView):
    feature_key = "customer_analysis"
    feature_error_message = "当前配置未启用客户分析"
    permission_map = {'get': 'reports:customer:view'}

    def get(self, request):
        data = CustomerReportService.get_activity(request.user)
        return Response(data)


class CustomerChurnView(ReportFeatureAPIView):
    feature_key = "customer_analysis"
    feature_error_message = "当前配置未启用客户分析"
    permission_map = {'get': 'reports:customer:view'}

    def get(self, request):
        data = CustomerReportService.get_churn(request.user)
        return Response(data)


class SupplierRankingView(ReportFeatureAPIView):
    feature_key = "supplier_analysis"
    feature_error_message = "当前配置未启用供应商分析"
    permission_map = {'get': 'reports:supplier:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = SupplierReportService.get_ranking(request.user, period, limit, start_date, end_date)
        return Response(data)


class SupplierActivityView(ReportFeatureAPIView):
    feature_key = "supplier_analysis"
    feature_error_message = "当前配置未启用供应商分析"
    permission_map = {'get': 'reports:supplier:view'}

    def get(self, request):
        data = SupplierReportService.get_activity(request.user)
        return Response(data)


class SupplierEvaluationView(ReportFeatureAPIView):
    feature_key = "supplier_analysis"
    feature_error_message = "当前配置未启用供应商分析"
    permission_map = {'get': 'reports:supplier:view'}

    def get(self, request):
        limit = int(request.query_params.get('limit', 20))
        data = SupplierReportService.get_evaluation_ranking(request.user, limit)
        return Response(data)


class ProductHotView(ReportFeatureAPIView):
    feature_key = "product_analysis"
    feature_error_message = "当前配置未启用商品分析"
    permission_map = {'get': 'reports:product:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        limit = int(request.query_params.get('limit', 20))
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        data = ProductReportService.get_hot_products(request.user, period, limit, start_date, end_date)
        return Response(data)


class ProductSlowView(ReportFeatureAPIView):
    feature_key = "product_analysis"
    feature_error_message = "当前配置未启用商品分析"
    permission_map = {'get': 'reports:product:view'}

    def get(self, request):
        days = int(request.query_params.get('days', 90))
        data = ProductReportService.get_slow_products(request.user, days)
        return Response(data)


class ProductInventoryView(ReportFeatureAPIView):
    feature_key = "product_analysis"
    feature_error_message = "当前配置未启用商品分析"
    permission_map = {'get': 'reports:product:view'}

    def get(self, request):
        data = ProductReportService.get_inventory_analysis(request.user)
        return Response(data)


class ExportView(ReportFeatureAPIView):
    feature_key = "export_center"
    feature_error_message = "当前配置未启用自定义导出"
    permission_map = {'post': 'reports:export:create'}

    def post(self, request):
        report_type = request.data.get('report_type')
        params = request.data.get('params', {})
        if not report_type:
            return Response({"detail": "缺少report_type"}, status=status.HTTP_400_BAD_REQUEST)

        task = ExportService.create_task(report_type, params, request.user)
        serializer = ReportExportTaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ExportTaskDetailView(ReportFeatureAPIView):
    feature_key = "export_center"
    feature_error_message = "当前配置未启用自定义导出"
    permission_map = {'get': 'reports:export:view'}

    def get(self, request, task_id):
        try:
            task = ReportExportTask.objects.get(id=task_id, created_by=request.user)
            serializer = ReportExportTaskSerializer(task)
            return Response(serializer.data)
        except ReportExportTask.DoesNotExist:
            return Response({"detail": "任务不存在"}, status=status.HTTP_404_NOT_FOUND)


class ExportTaskListView(ReportFeatureAPIView):
    """导出任务列表"""
    feature_key = "export_center"
    feature_error_message = "当前配置未启用自定义导出"
    permission_map = {'get': 'reports:export:view'}

    def get(self, request):
        qs = ReportExportTask.objects.filter(created_by=request.user).order_by('-created_at')[:50]
        serializer = ReportExportTaskSerializer(qs, many=True)
        return Response(serializer.data)


class SalesDrillView(ReportFeatureAPIView):
    """销售钻取：从汇总/排行点击进入订单列表"""
    feature_key = "sales_analysis"
    feature_error_message = "当前配置未启用销售分析"
    permission_map = {'get': 'reports:sales:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        product_id = request.query_params.get('product_id')
        customer_id = request.query_params.get('customer_id')

        orders = SalesReportService.get_drill_orders(
            request.user, period, start_date, end_date,
            product_id=product_id, customer_id=customer_id,
        )
        data = [{
            'id': o.id, 'order_no': o.order_no, 'customer_name': o.customer_name_snapshot,
            'total_amount': str(o.total_amount), 'status': o.status,
            'created_at': o.created_at.isoformat(),
        } for o in orders]
        return Response(data)


class PurchaseDrillView(ReportFeatureAPIView):
    """采购钻取：从排行点击进入订单列表"""
    feature_key = "purchase_analysis"
    feature_error_message = "当前配置未启用采购分析"
    permission_map = {'get': 'reports:purchase:view'}

    def get(self, request):
        period = request.query_params.get('period', 'month')
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        product_id = request.query_params.get('product_id')
        supplier_id = request.query_params.get('supplier_id')

        orders = PurchaseReportService.get_drill_orders(
            request.user, period, start_date, end_date,
            product_id=product_id, supplier_id=supplier_id,
        )
        data = [{
            'id': o.id, 'purchase_order_no': o.purchase_order_no,
            'supplier_name': o.supplier_name_snapshot,
            'total_amount': str(o.total_amount), 'status': o.status,
            'created_at': o.created_at.isoformat(),
        } for o in orders]
        return Response(data)
