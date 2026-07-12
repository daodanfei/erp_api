from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import APAccountViewSet, APAllocationViewSet, APPaymentViewSet, SupplierRefundViewSet

router = DefaultRouter()
router.register('accounts', APAccountViewSet)
router.register('payments', APPaymentViewSet)
router.register('refunds', SupplierRefundViewSet)
router.register('allocations', APAllocationViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
