from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import OperationLogViewSet

router = DefaultRouter()
router.register("logs", OperationLogViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
