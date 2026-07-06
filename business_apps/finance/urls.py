from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FinanceViewSet, CashAccountViewSet, ExportTaskViewSet

router = DefaultRouter()
router.register('cash-accounts', CashAccountViewSet)
router.register('export-tasks', ExportTaskViewSet)
router.register('', FinanceViewSet, basename='finance')

urlpatterns = [
    path('', include(router.urls)),
]
