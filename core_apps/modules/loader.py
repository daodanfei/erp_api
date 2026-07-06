from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from pkgutil import iter_modules

import business_apps
import core_apps

from .checks import ModuleRegistryError, validate_modules


def load_business_modules():
    return _load_modules_from_package(
        package_root=business_apps,
        package_namespace="business_apps",
        package_label="business app",
        require_manifest=True,
        manifest_root="backend/business_apps",
    )


def load_core_modules():
    return _load_modules_from_package(
        package_root=core_apps,
        package_namespace="core_apps",
        package_label="core app",
        require_manifest=False,
        manifest_root="backend/core_apps",
    )


def _load_modules_from_package(
    *,
    package_root,
    package_namespace: str,
    package_label: str,
    require_manifest: bool,
    manifest_root: str,
):
    modules = []
    for package in iter_modules(package_root.__path__):
        if not package.ispkg:
            continue

        module_path = f"{package_namespace}.{package.name}.module"
        manifest_spec = find_spec(module_path)
        if manifest_spec is None:
            if require_manifest:
                raise ModuleRegistryError(
                    f"Missing module manifest for {package_label} '{package.name}'. "
                    f"Expected file: {manifest_root}/{package.name}/module.py"
                )
            continue

        try:
            manifest = import_module(module_path)
        except Exception as exc:
            raise ModuleRegistryError(
                f"Failed to import module manifest '{module_path}': {exc}"
            ) from exc

        if not hasattr(manifest, "MODULE"):
            raise ModuleRegistryError(
                f"Module manifest '{module_path}' is missing required export 'MODULE'."
            )

        modules.append(manifest.MODULE)

    ordered_modules = _topological_sort(modules)
    validate_modules(
        ordered_modules,
        validate_manifest_codes=package_namespace != "core_apps",
    )
    return tuple(ordered_modules)


def _topological_sort(modules):
    modules_by_key = {module.key: module for module in modules}
    ordered = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_key: str) -> None:
        if module_key in visited:
            return
        if module_key in visiting:
            return

        visiting.add(module_key)
        module = modules_by_key[module_key]
        for dependency in module.depends_on:
            if dependency in modules_by_key:
                visit(dependency)
        visiting.remove(module_key)
        visited.add(module_key)
        ordered.append(module)

    for module in sorted(modules, key=lambda item: item.key):
        visit(module.key)

    return ordered
