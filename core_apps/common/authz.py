from core_apps.authentication.models import User as PlatformUser
from core_apps.erp_auth.models import ERPUser


def has_platform_role_permission(user: PlatformUser, permission_code: str) -> bool:
    if not isinstance(user, PlatformUser) or not user.is_authenticated:
        return False
    return user.roles.filter(
        permissions__code=permission_code,
        permissions__status=True,
        status=True,
    ).exists()


def has_erp_role_permission(user: ERPUser, permission_code: str) -> bool:
    if not isinstance(user, ERPUser) or not user.is_authenticated:
        return False
    return user.roles.filter(
        permissions__code=permission_code,
        permissions__status=True,
        status=True,
    ).exists()


def has_platform_full_data_scope(user: PlatformUser) -> bool:
    if not isinstance(user, PlatformUser) or not user.is_authenticated:
        return False
    return user.roles.filter(status=True, data_scope="ALL").exists()


def has_erp_full_data_scope(user: ERPUser) -> bool:
    if not isinstance(user, ERPUser) or not user.is_authenticated:
        return False
    return user.roles.filter(status=True, data_scope="ALL").exists()
