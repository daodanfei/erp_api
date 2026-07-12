from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerRefundViewSet, ReceivableViewSet, ReceiptViewSet, WriteOffViewSet

router = DefaultRouter()
router.register('receivables', ReceivableViewSet)
router.register('receipts', ReceiptViewSet)
router.register('refunds', CustomerRefundViewSet)
router.register('write-offs', WriteOffViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
