from django.urls import path
from .views import (
    DashboardView, SalesSummaryView, SalesTrendView, SalesProductRankingView, SalesCustomerRankingView,
    PurchaseSummaryView, PurchaseTrendView, PurchaseSupplierRankingView, PurchaseProductRankingView,
    InventorySummaryView, InventoryAgingView, InventoryAlertsView, InventoryTransactionSummaryView,
    CustomerStatsView, CustomerRankingView, CustomerActivityView, CustomerChurnView,
    SupplierRankingView, SupplierActivityView, SupplierEvaluationView,
    ProductHotView, ProductSlowView, ProductInventoryView,
    ExportView, ExportTaskDetailView, ExportTaskListView,
    SalesDrillView, PurchaseDrillView,
)

urlpatterns = [
    # 经营驾驶舱
    path('dashboard', DashboardView.as_view(), name='dashboard'),

    # 销售分析
    path('sales/summary', SalesSummaryView.as_view(), name='sales-summary'),
    path('sales/trend', SalesTrendView.as_view(), name='sales-trend'),
    path('sales/products', SalesProductRankingView.as_view(), name='sales-products'),
    path('sales/customers', SalesCustomerRankingView.as_view(), name='sales-customers'),
    path('sales/drill', SalesDrillView.as_view(), name='sales-drill'),

    # 采购分析
    path('purchase/summary', PurchaseSummaryView.as_view(), name='purchase-summary'),
    path('purchase/trend', PurchaseTrendView.as_view(), name='purchase-trend'),
    path('purchase/suppliers', PurchaseSupplierRankingView.as_view(), name='purchase-suppliers'),
    path('purchase/products', PurchaseProductRankingView.as_view(), name='purchase-products'),
    path('purchase/drill', PurchaseDrillView.as_view(), name='purchase-drill'),

    # 库存分析
    path('inventory/summary', InventorySummaryView.as_view(), name='inventory-summary'),
    path('inventory/aging', InventoryAgingView.as_view(), name='inventory-aging'),
    path('inventory/alerts', InventoryAlertsView.as_view(), name='inventory-alerts'),
    path('inventory/transactions', InventoryTransactionSummaryView.as_view(), name='inventory-transactions'),

    # 客户分析
    path('customers/stats', CustomerStatsView.as_view(), name='customer-stats'),
    path('customers/ranking', CustomerRankingView.as_view(), name='customer-ranking'),
    path('customers/activity', CustomerActivityView.as_view(), name='customer-activity'),
    path('customers/churn', CustomerChurnView.as_view(), name='customer-churn'),

    # 供应商分析
    path('suppliers/ranking', SupplierRankingView.as_view(), name='supplier-ranking'),
    path('suppliers/activity', SupplierActivityView.as_view(), name='supplier-activity'),
    path('suppliers/evaluation', SupplierEvaluationView.as_view(), name='supplier-evaluation'),

    # 商品分析
    path('products/hot', ProductHotView.as_view(), name='product-hot'),
    path('products/slow', ProductSlowView.as_view(), name='product-slow'),
    path('products/inventory', ProductInventoryView.as_view(), name='product-inventory'),

    # 导出
    path('export', ExportView.as_view(), name='export'),
    path('export/tasks', ExportTaskListView.as_view(), name='export-tasks'),
    path('export/<int:task_id>', ExportTaskDetailView.as_view(), name='export-detail'),
]
