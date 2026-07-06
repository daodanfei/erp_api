from rest_framework.routers import DefaultRouter
from .views import (
    OutboundOrderViewSet,
    TransferOrderViewSet,
    SalesReturnOrderViewSet,
    PurchaseReturnOrderViewSet,
    InventoryAlertViewSet,
    InventoryTraceViewSet,
)

router = DefaultRouter()
router.register('outbound-orders', OutboundOrderViewSet)
router.register('transfer-orders', TransferOrderViewSet)
router.register('sales-returns', SalesReturnOrderViewSet)
router.register('purchase-returns', PurchaseReturnOrderViewSet)
router.register('alerts', InventoryAlertViewSet)
router.register('trace', InventoryTraceViewSet, basename='inventory-trace')

urlpatterns = router.urls
