from __future__ import annotations

import secrets
from dataclasses import dataclass

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from core_apps.modules import get_erp_permission_modules

from .models import ERPPermission, ERPRole, ERPUser


# These pages stay in code for compatibility, but ERP tenants should not grant or
# expose their permissions by default.
ERP_DEFAULT_HIDDEN_PERMISSION_CODES = {
    "system:perm",
}
ERP_DEFAULT_HIDDEN_PERMISSION_PREFIXES = (
    "platform:dict",
    "platform:coderule",
)

SYSTEM_FEATURE_PERMISSION_CODES = {
    "user_management": {
        "system:user",
        "user:create",
        "user:update",
        "user:delete",
    },
    "department_management": {
        "system:dept",
    },
    "role_management": {
        "system:role",
    },
    "operation_log": {
        "system:log",
    },
    "permission_management": {
        "system:perm",
    },
}
SYSTEM_MANAGED_PERMISSION_CODES = {
    code
    for permission_codes in SYSTEM_FEATURE_PERMISSION_CODES.values()
    for code in permission_codes
} | {"system"}


def generate_erp_role_code(*, tenant_code: str, role_name: str) -> str:
    base = slugify(role_name, allow_unicode=False).replace("_", "-").strip("-") or "role"
    candidate = f"{tenant_code}-{base}"
    suffix = 2
    while ERPRole.objects.filter(tenant__code=tenant_code, code=candidate).exists():
        candidate = f"{tenant_code}-{base}-{suffix}"
        suffix += 1
    return candidate


def generate_initial_erp_password() -> str:
    return secrets.token_urlsafe(12)


def _iter_erp_permission_definitions():
    for module in get_erp_permission_modules():
        for menu in module.menus:
            yield module.key, {
                "code": menu["code"],
                "name": menu["name"],
                "type": "MENU",
                "parent": menu.get("parent"),
                "path": menu.get("path"),
                "component": menu.get("component"),
                "icon": menu.get("icon"),
                "hide_in_menu": menu.get("hide_in_menu", False),
                "order": menu.get("order", 0),
                "status": menu.get("status", True),
            }
        for permission in module.permissions:
            yield module.key, {
                "code": permission["code"],
                "name": permission["name"],
                "type": "BUTTON",
                "parent": permission.get("parent"),
                "path": permission.get("path"),
                "component": permission.get("component"),
                "icon": permission.get("icon"),
                "hide_in_menu": permission.get("hide_in_menu", False),
                "order": permission.get("order", 0),
                "status": permission.get("status", True),
            }


def get_defined_erp_permission_codes() -> set[str]:
    return {definition["code"] for _, definition in _iter_erp_permission_definitions()}


def _is_hidden_for_erp(code: str) -> bool:
    return code in ERP_DEFAULT_HIDDEN_PERMISSION_CODES or code.startswith(ERP_DEFAULT_HIDDEN_PERMISSION_PREFIXES)


def get_enabled_erp_permission_codes(*, tenant) -> set[str]:
    from core_apps.tenant.services import TenantService

    runtime_config = TenantService.get_runtime_config(tenant)
    enabled_modules = set(runtime_config.enabled_modules())
    enabled_modules.add("erp_auth")
    enabled_codes = {
        definition["code"]
        for module_key, definition in _iter_erp_permission_definitions()
        if module_key in enabled_modules and not _is_hidden_for_erp(definition["code"])
    }
    enabled_codes -= SYSTEM_MANAGED_PERMISSION_CODES
    if runtime_config.is_enabled("system"):
        system_feature_codes = set()
        for feature_key, permission_codes in SYSTEM_FEATURE_PERMISSION_CODES.items():
            if runtime_config.is_feature_enabled("system", feature_key):
                system_feature_codes.update(permission_codes)
        if system_feature_codes:
            system_feature_codes.add("system")
        enabled_codes |= system_feature_codes
    return enabled_codes


def sync_erp_permissions() -> dict[str, ERPPermission]:
    definitions = list(_iter_erp_permission_definitions())
    existing = {permission.code: permission for permission in ERPPermission.objects.all()}
    synced: dict[str, ERPPermission] = {}

    for _, definition in definitions:
        code = definition["code"]
        defaults = {
            "name": definition["name"],
            "type": definition["type"],
            "path": definition.get("path"),
            "component": definition.get("component"),
            "icon": definition.get("icon"),
            "hide_in_menu": definition.get("hide_in_menu", False),
            "order": definition.get("order", 0),
            "status": definition.get("status", True),
        }
        erp_permission = existing.get(code)
        if erp_permission is None:
            erp_permission = ERPPermission.objects.create(code=code, **defaults)
        else:
            changed = False
            for field_name, field_value in defaults.items():
                if getattr(erp_permission, field_name) != field_value:
                    setattr(erp_permission, field_name, field_value)
                    changed = True
            if changed:
                erp_permission.save(update_fields=list(defaults.keys()))
        synced[code] = erp_permission

    for _, definition in definitions:
        erp_permission = synced[definition["code"]]
        parent_code = definition.get("parent")
        parent = synced.get(parent_code) if parent_code else None
        if erp_permission.parent_id != getattr(parent, "id", None):
            erp_permission.parent = parent
            erp_permission.save(update_fields=["parent"])

    return synced


@dataclass(frozen=True, slots=True)
class ERPAdminProvisionResult:
    user: ERPUser
    role: ERPRole
    initial_password: str
    created: bool


class ERPUserProvisionService:
    @staticmethod
    def ensure_tenant_user_capacity(*, tenant, extra_users: int = 1) -> None:
        if tenant.user_limit is None:
            return
        if tenant.erp_users.count() + extra_users > tenant.user_limit:
            raise ValidationError("租户用户数已达上限")

    @staticmethod
    def get_tenant_super_admin(*, tenant) -> ERPUser | None:
        return (
            tenant.erp_users
            .prefetch_related("roles")
            .filter(roles__is_system=True, roles__data_scope="ALL", roles__status=True)
            .order_by("id")
            .distinct()
            .first()
        )

    @staticmethod
    @transaction.atomic
    def reset_password(*, user: ERPUser) -> str:
        initial_password = generate_initial_erp_password()
        user.set_password(initial_password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        return initial_password

    @staticmethod
    @transaction.atomic
    def ensure_super_admin_role(*, user: ERPUser) -> ERPRole:
        tenant = user.tenant
        permission_map = sync_erp_permissions()
        enabled_codes = get_enabled_erp_permission_codes(tenant=tenant)
        all_permissions = [
            permission
            for code, permission in permission_map.items()
            if code in enabled_codes and permission.status
        ]
        role = user.roles.filter(is_system=True, data_scope="ALL").order_by("id").first()
        if role is None:
            role = ERPRole.objects.create(
                tenant=tenant,
                name="租户超级管理员",
                code=generate_erp_role_code(tenant_code=tenant.code, role_name="tenant-admin"),
                data_scope="ALL",
                status=True,
                is_system=True,
            )
        role.permissions.set(all_permissions)
        user.roles.add(role)
        return role

    @staticmethod
    @transaction.atomic
    def ensure_tenant_super_admin(*, tenant, username: str = "admin") -> ERPAdminProvisionResult:
        existing_user = ERPUserProvisionService.get_tenant_super_admin(tenant=tenant)
        if existing_user is not None:
            existing_role = ERPUserProvisionService.ensure_super_admin_role(user=existing_user)
            return ERPAdminProvisionResult(
                user=existing_user,
                role=existing_role,
                initial_password="",
                created=False,
            )

        ERPUserProvisionService.ensure_tenant_user_capacity(tenant=tenant)
        initial_password = generate_initial_erp_password()
        user = ERPUser.objects.create_user(
            tenant=tenant,
            username=username,
            password=initial_password,
            name="租户超级管理员",
            status=True,
            must_change_password=True,
        )
        role = ERPUserProvisionService.ensure_super_admin_role(user=user)
        user.roles.add(role)
        return ERPAdminProvisionResult(
            user=user,
            role=role,
            initial_password=initial_password,
            created=True,
        )
