from __future__ import annotations

from collections import Counter
import re
from typing import Iterable


class ModuleRegistryError(ValueError):
    """Raised when module manifests are inconsistent."""


def validate_modules(modules: Iterable[object], *, validate_manifest_codes: bool = True) -> None:
    module_list = list(modules)
    _ensure_required_module_fields(module_list)
    _ensure_unique(module_list, "key")
    _ensure_unique(module_list, "django_app")
    _ensure_unique(module_list, "api_prefix")
    _ensure_dependencies_exist(module_list)
    _ensure_no_dependency_cycles(module_list)
    if validate_manifest_codes:
        _ensure_menu_integrity(module_list)
        _ensure_permission_integrity(module_list)
    _ensure_public_services_are_valid(module_list)


def _ensure_required_module_fields(modules: list[object]) -> None:
    required_fields = ("key", "label", "django_app", "api_prefix")
    for module in modules:
        for field_name in required_fields:
            value = getattr(module, field_name, None)
            if not isinstance(value, str) or not value.strip():
                raise ModuleRegistryError(
                    f"Module {getattr(module, 'key', '<unknown>')} is missing required "
                    f"field '{field_name}'."
                )

        for collection_name in (
            "depends_on",
            "permissions",
            "menus",
            "features",
            "workflows",
            "field_rules",
            "default_rules",
            "public_services",
        ):
            value = getattr(module, collection_name, None)
            if value is None:
                raise ModuleRegistryError(
                    f"Module {module.key} is missing required field '{collection_name}'."
                )

        if not re.fullmatch(r"api/[a-z0-9][a-z0-9-]*/", module.api_prefix):
            raise ModuleRegistryError(
                f"Module {module.key} has invalid api_prefix '{module.api_prefix}'. "
                "Use the full API prefix form like 'api/inventory/'."
            )


def _ensure_unique(modules: list[object], field_name: str) -> None:
    counts = Counter(getattr(module, field_name) for module in modules)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if duplicates:
        raise ModuleRegistryError(
            f"Duplicate module {field_name} values: {', '.join(duplicates)}"
        )


def _ensure_dependencies_exist(modules: list[object]) -> None:
    module_keys = {module.key for module in modules}
    missing: list[str] = []
    for module in modules:
        for dependency in module.depends_on:
            if dependency not in module_keys:
                missing.append(f"{module.key}->{dependency}")
    if missing:
        raise ModuleRegistryError(
            "Unknown module dependencies: " + ", ".join(sorted(missing))
        )


def _ensure_no_dependency_cycles(modules: list[object]) -> None:
    dependencies = {module.key: tuple(module.depends_on) for module in modules}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str, trail: tuple[str, ...]) -> None:
        if key in visited:
            return
        if key in visiting:
            cycle = " -> ".join((*trail, key))
            raise ModuleRegistryError(f"Module dependency cycle detected: {cycle}")

        visiting.add(key)
        for dependency in dependencies[key]:
            visit(dependency, (*trail, key))
        visiting.remove(key)
        visited.add(key)

    for key in dependencies:
        visit(key, ())


def _ensure_menu_integrity(modules: list[object]) -> None:
    menus = [
        (module.key, menu)
        for module in modules
        for menu in getattr(module, "menus", ())
    ]
    _ensure_manifest_item_fields(menus, "menu", ("code", "name", "path"))
    _ensure_item_field_uniqueness(menus, "menu", "code")
    _ensure_item_field_uniqueness(menus, "menu", "path")
    _ensure_menu_parents_exist(menus)


def _ensure_permission_integrity(modules: list[object]) -> None:
    permissions = [
        (module.key, permission)
        for module in modules
        for permission in getattr(module, "permissions", ())
    ]
    _ensure_manifest_item_fields(permissions, "permission", ("code", "name", "parent"))
    _ensure_item_field_uniqueness(permissions, "permission", "code")
    _ensure_menu_and_permission_codes_do_not_overlap(modules, permissions)
    _ensure_permission_parents_exist(modules, permissions)


def _ensure_manifest_item_fields(
    items: list[tuple[str, object]],
    item_label: str,
    required_fields: tuple[str, ...],
) -> None:
    for module_key, item in items:
        if not isinstance(item, dict):
            raise ModuleRegistryError(
                f"Module {module_key} has non-dict {item_label} definition: {item!r}"
            )
        for field_name in required_fields:
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ModuleRegistryError(
                    f"Module {module_key} has {item_label} missing required field "
                    f"'{field_name}': {item!r}"
                )


def _ensure_item_field_uniqueness(
    items: list[tuple[str, dict]],
    item_label: str,
    field_name: str,
) -> None:
    index: dict[str, list[str]] = {}
    for module_key, item in items:
        index.setdefault(item[field_name], []).append(module_key)

    duplicates = sorted(
        f"{value} ({', '.join(sorted(set(module_keys)))})"
        for value, module_keys in index.items()
        if len(module_keys) > 1
    )
    if duplicates:
        raise ModuleRegistryError(
            f"Duplicate {item_label} {field_name} values: {', '.join(duplicates)}"
        )


def _ensure_menu_parents_exist(menus: list[tuple[str, dict]]) -> None:
    menu_codes = {menu["code"] for _, menu in menus}
    missing: list[str] = []
    for module_key, menu in menus:
        parent = menu.get("parent")
        if parent and parent not in menu_codes:
            missing.append(f"{module_key}:{menu['code']}->{parent}")
    if missing:
        raise ModuleRegistryError(
            "Unknown menu parents: " + ", ".join(sorted(missing))
        )


def _ensure_permission_parents_exist(
    modules: list[object],
    permissions: list[tuple[str, dict]],
) -> None:
    menu_codes = {
        menu["code"]
        for module in modules
        for menu in getattr(module, "menus", ())
    }
    missing: list[str] = []
    for module_key, permission in permissions:
        parent = permission.get("parent")
        if parent not in menu_codes:
            missing.append(f"{module_key}:{permission['code']}->{parent}")
    if missing:
        raise ModuleRegistryError(
            "Permission parent menus not found: " + ", ".join(sorted(missing))
        )


def _ensure_menu_and_permission_codes_do_not_overlap(
    modules: list[object],
    permissions: list[tuple[str, dict]],
) -> None:
    menu_codes = {
        menu["code"]
        for module in modules
        for menu in getattr(module, "menus", ())
    }
    permission_codes = {permission["code"] for _, permission in permissions}
    overlaps = sorted(menu_codes & permission_codes)
    if overlaps:
        raise ModuleRegistryError(
            "Menu codes and permission codes must not overlap: "
            + ", ".join(overlaps)
        )


def _ensure_public_services_are_valid(modules: list[object]) -> None:
    pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
    for module in modules:
        for service in getattr(module, "public_services", ()):
            if not isinstance(service, str) or not pattern.fullmatch(service):
                raise ModuleRegistryError(
                    f"Module {module.key} has invalid public_services entry: {service!r}"
                )
