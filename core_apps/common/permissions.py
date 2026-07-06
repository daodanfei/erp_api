from rest_framework import permissions

from core_apps.authentication.models import User as PlatformUser
from core_apps.erp_auth.models import ERPUser
from core_apps.tenant.services import TenantService
from core_apps.policies.registry import get_runtime_config_for_user

from .authz import has_erp_role_permission, has_platform_role_permission


def _resolve_required_code(view, request):
    permission_map = getattr(view, "permission_map", {})
    action = getattr(view, "action", None)
    required_code = permission_map.get(action)
    if not required_code and action == "partial_update":
        required_code = permission_map.get("update")
    if not required_code:
        required_code = permission_map.get(request.method.lower())
    return required_code


class PlatformActionPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not isinstance(user, PlatformUser) or not user.is_authenticated:
            return False
        required_code = _resolve_required_code(view, request)
        if not required_code:
            return True
        return has_platform_role_permission(user, required_code)


class ERPActionPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not isinstance(user, ERPUser) or not user.is_authenticated:
            return False
        required_code = _resolve_required_code(view, request)
        if not required_code:
            return True
        return has_erp_role_permission(user, required_code)


class ModuleEnabledPermission(permissions.BasePermission):
    message = "当前租户未启用该模块"

    def has_permission(self, request, view):
        module_key = getattr(view, "module_key", "")
        if not module_key:
            return True
        if isinstance(request.user, ERPUser):
            runtime_config = TenantService.get_runtime_config(request.user.tenant)
        else:
            runtime_config = getattr(request, "tenant_config", None) or get_runtime_config_for_user(request.user)
        return runtime_config.is_enabled(module_key)


class PlatformUserOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, PlatformUser)


class ERPUserOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, ERPUser)
