from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SalesOrderViewSet

router = DefaultRouter()
router.register('orders', SalesOrderViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
