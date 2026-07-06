from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import APAccountViewSet, APPaymentViewSet, APAllocationViewSet

router = DefaultRouter()
router.register('accounts', APAccountViewSet)
router.register('payments', APPaymentViewSet)
router.register('allocations', APAllocationViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
