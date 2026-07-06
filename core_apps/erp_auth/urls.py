from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ERPChangePasswordView,
    ERPDepartmentViewSet,
    ERPLoginView,
    ERPMeView,
    ERPPermissionViewSet,
    ERPRoleViewSet,
    ERPTokenRefreshView,
    ERPUserViewSet,
)

router = DefaultRouter()
router.register("users", ERPUserViewSet, basename="erp-user")
router.register("roles", ERPRoleViewSet, basename="erp-role")
router.register("permissions", ERPPermissionViewSet, basename="erp-permission")
router.register("departments", ERPDepartmentViewSet, basename="erp-department")

urlpatterns = [
    path("login/", ERPLoginView.as_view()),
    path("refresh/", ERPTokenRefreshView.as_view()),
    path("me/", ERPMeView.as_view()),
    path("change-password/", ERPChangePasswordView.as_view()),
    path("", include(router.urls)),
]
