from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

from .checks import validate_modules
from .loader import load_business_modules, load_core_modules


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    key: str
    label: str
    django_app: str
    api_prefix: str
    depends_on: tuple[str, ...] = ()
    permissions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    menus: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    features: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    field_rules: tuple[str, ...] = ()
    default_rules: tuple[str, ...] = ()
    public_services: tuple[str, ...] = ()
    export_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def urlconf(self) -> str:
        return f"{self.django_app}.urls"


@lru_cache(maxsize=1)
def get_business_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(load_business_modules())


@lru_cache(maxsize=1)
def get_core_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(load_core_modules())


@lru_cache(maxsize=1)
def get_permission_modules() -> tuple[ModuleDefinition, ...]:
    modules = (*get_core_modules(), *get_business_modules())
    validate_modules(modules, validate_manifest_codes=False)
    return modules


@lru_cache(maxsize=1)
def get_platform_permission_modules() -> tuple[ModuleDefinition, ...]:
    modules = tuple(module for module in get_core_modules() if module.key != "erp_auth")
    validate_modules(modules)
    return modules


def _expand_core_dependencies(initial_keys: set[str]) -> tuple[ModuleDefinition, ...]:
    modules_by_key = {module.key: module for module in get_core_modules()}
    selected_keys = set(initial_keys)
    pending = list(initial_keys)

    while pending:
        module_key = pending.pop()
        module = modules_by_key.get(module_key)
        if module is None:
            continue
        for dependency in module.depends_on:
            if dependency in modules_by_key and dependency not in selected_keys:
                selected_keys.add(dependency)
                pending.append(dependency)

    return tuple(module for module in get_core_modules() if module.key in selected_keys)


def _without_permission_manifest(module: ModuleDefinition) -> ModuleDefinition:
    return replace(module, menus=(), permissions=())


@lru_cache(maxsize=1)
def get_erp_permission_modules() -> tuple[ModuleDefinition, ...]:
    core_modules = tuple(
        module if module.key == "erp_auth" else _without_permission_manifest(module)
        for module in _expand_core_dependencies({"erp_auth"})
    )
    modules = (*core_modules, *get_business_modules())
    validate_modules(modules)
    return modules


def get_business_django_apps() -> list[str]:
    return [module.django_app for module in get_business_modules()]


def get_core_django_apps() -> list[str]:
    return [module.django_app for module in get_core_modules()]


def get_core_urlpatterns() -> list[tuple[str, str]]:
    return [(module.api_prefix, module.urlconf) for module in get_core_modules()]


def get_business_urlpatterns() -> list[tuple[str, str]]:
    return [(module.api_prefix, module.urlconf) for module in get_business_modules()]
