from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PurchaseOrderViewSet, PurchaseReceiptViewSet

router = DefaultRouter()
router.register('orders', PurchaseOrderViewSet)
router.register('receipts', PurchaseReceiptViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
