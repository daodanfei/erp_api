import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core_project.settings")
django.setup()

from core_apps.authentication.models import Permission, Role, User
from core_apps.modules import get_platform_permission_modules

# Backward-compatible alias for tests and legacy callers.
get_permission_modules = get_platform_permission_modules


def seed_data():
    print("Starting permission seeding...")

    admin_role, _ = Role.objects.get_or_create(
        code="admin",
        defaults={"name": "超级管理员", "data_scope": "ALL"},
    )

    menu_objects = _sync_menus()
    _sync_buttons(menu_objects)

    admin_permission_codes = get_platform_admin_permission_codes()
    admin_permissions = Permission.objects.filter(code__in=admin_permission_codes)
    admin_role.permissions.set(admin_permissions)

    admin_user = User.objects.filter(username="admin").first()
    if admin_user:
        admin_user.roles.add(admin_role)


def get_defined_permission_codes() -> set[str]:
    codes: set[str] = set()
    for module in get_permission_modules():
        for menu in module.menus:
            codes.add(menu["code"])
        for permission in module.permissions:
            codes.add(permission["code"])
    return codes


def get_platform_admin_permission_codes() -> set[str]:
    return get_defined_permission_codes()


def _sync_menus() -> dict[str, Permission]:
    menus = []
    for module in get_permission_modules():
        menus.extend(module.menus)

    pending = list(sorted(menus, key=_menu_sort_key))
    created: dict[str, Permission] = {}

    while pending:
        next_pending = []
        progressed = False

        for menu in pending:
            parent_code = menu.get("parent")
            if parent_code and parent_code not in created:
                next_pending.append(menu)
                continue

            defaults = {
                "name": menu["name"],
                "type": "MENU",
                "parent": created.get(parent_code),
                "path": menu.get("path"),
                "component": menu.get("component"),
                "icon": menu.get("icon"),
                "hide_in_menu": menu.get("hide_in_menu", False),
                "order": menu.get("order", 0),
                "status": menu.get("status", True),
            }
            permission, _ = Permission.objects.update_or_create(
                code=menu["code"],
                defaults=defaults,
            )
            created[menu["code"]] = permission
            progressed = True

        if not progressed:
            unresolved = ", ".join(
                f"{menu['code']}->{menu.get('parent')}" for menu in next_pending
            )
            raise ValueError(f"Unable to resolve menu parents: {unresolved}")

        pending = next_pending

    return created


def _sync_buttons(menu_objects: dict[str, Permission]) -> None:
    buttons = []
    for module in get_permission_modules():
        buttons.extend(module.permissions)

    for button in buttons:
        parent = menu_objects.get(button.get("parent"))
        if parent is None:
            raise ValueError(
                f"Button permission {button['code']} references unknown parent "
                f"{button.get('parent')}"
            )

        defaults = {
            "name": button["name"],
            "type": "BUTTON",
            "parent": parent,
            "path": button.get("path"),
            "component": button.get("component"),
            "icon": button.get("icon"),
            "hide_in_menu": button.get("hide_in_menu", False),
            "order": button.get("order", 0),
            "status": button.get("status", True),
        }
        Permission.objects.update_or_create(
            code=button["code"],
            defaults=defaults,
        )


def _menu_sort_key(menu: dict) -> tuple[int, str]:
    return (int(menu.get("order", 0) * 10), menu["code"])


if __name__ == "__main__":
    seed_data()
