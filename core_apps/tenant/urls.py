from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RuntimeConfigView, TenantConfigSnapshotViewSet, TenantModuleStateViewSet, TenantUserViewSet, TenantViewSet

router = DefaultRouter()
router.register("items", TenantViewSet, basename="tenant")
router.register("users", TenantUserViewSet, basename="tenant-user")
router.register("module-states", TenantModuleStateViewSet, basename="tenant-module-state")
router.register("config-snapshots", TenantConfigSnapshotViewSet, basename="tenant-config-snapshot")

urlpatterns = [
    path("runtime-config/", RuntimeConfigView.as_view()),
    path("", include(router.urls)),
]
