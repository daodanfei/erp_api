from __future__ import annotations

from dataclasses import asdict, dataclass

from core_apps.blueprints.models import SystemBlueprintVersion
from core_apps.configuration import validate_blueprint_config
from core_apps.modules import get_business_modules, get_core_modules


RUNTIME_BASE_MODULE_KEYS = ("system", "organization", "authentication", "configuration", "tenant")
EXPORT_BASE_FRONTEND_MODULES = ("auth", "home", "system")
FRONTEND_MODULE_KEY_MAP = {
    "ap_payable": "apPayable",
    "ar_receivable": "arReceivable",
    "supply_chain": "supplyChain",
}
EXPORT_CONFIG_FILES = (
    "backend/manage.py",
    "backend/requirements.txt",
    "backend/core_project/settings.py",
    "backend/core_project/urls.py",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.app.json",
    "frontend/vite.config.ts",
    "frontend/src/App.tsx",
    "frontend/src/main.tsx",
)


@dataclass(frozen=True, slots=True)
class PlannedModule:
    key: str
    label: str
    django_app: str
    api_prefix: str
    depends_on: tuple[str, ...]
    frontend_module_key: str | None


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    runtime_mode: str
    enabled_modules: tuple[str, ...]
    module_configs: dict
    module_keys: tuple[str, ...]
    modules: tuple[PlannedModule, ...]
    retained_frontend_modules: tuple[str, ...]
    retained_backend_apps: tuple[str, ...]
    removed_modules: tuple[str, ...]
    retained_feature_behaviors: dict
    module_dependency_graph: dict
    module_feature_contracts: dict
    prunable_route_paths: tuple[str, ...]
    prunable_permission_codes: tuple[str, ...]
    seed_data_requirements: dict
    support_dependencies: dict
    exported_config_files: tuple[str, ...]
    export_manifest: dict
    steps: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "runtime_mode": self.runtime_mode,
            "enabled_modules": list(self.enabled_modules),
            "module_configs": self.module_configs,
            "module_keys": list(self.module_keys),
            "modules": [asdict(module) for module in self.modules],
            "retained_frontend_modules": list(self.retained_frontend_modules),
            "retained_backend_apps": list(self.retained_backend_apps),
            "removed_modules": list(self.removed_modules),
            "retained_feature_behaviors": self.retained_feature_behaviors,
            "module_dependency_graph": self.module_dependency_graph,
            "module_feature_contracts": self.module_feature_contracts,
            "prunable_route_paths": list(self.prunable_route_paths),
            "prunable_permission_codes": list(self.prunable_permission_codes),
            "seed_data_requirements": self.seed_data_requirements,
            "support_dependencies": self.support_dependencies,
            "exported_config_files": list(self.exported_config_files),
            "export_manifest": self.export_manifest,
            "steps": list(self.steps),
        }


def resolve_runtime_mode(config_json: dict) -> str:
    normalized = validate_blueprint_config(config_json)
    mode = normalized["basic"]["mode"]
    return "SAAS" if mode == "saas" else "CODE_EXPORT"


def resolve_enabled_modules(config_json: dict) -> tuple[str, ...]:
    normalized = validate_blueprint_config(config_json)
    return tuple(normalized["enabled_modules"])


def resolve_feature_plan(config_json: dict) -> dict:
    normalized = validate_blueprint_config(config_json)
    plan = {}
    for module_key in normalized["enabled_modules"]:
        module_config = normalized["module_configs"].get(module_key, {})
        plan[module_key] = {
            "features": {
                key: value for key, value in module_config.get("features", {}).items() if bool(value)
            },
            "workflows": module_config.get("workflows", {}),
            "defaults": module_config.get("defaults", {}),
            "field_rules": module_config.get("field_rules", {}),
        }
    return plan


def build_export_manifest(*, blueprint_version: SystemBlueprintVersion, plan: GenerationPlan) -> dict:
    return {
        "blueprint": {
            "id": blueprint_version.blueprint_id,
            "key": blueprint_version.blueprint.key,
            "name": blueprint_version.blueprint.name,
            "version_id": blueprint_version.id,
            "version": blueprint_version.version,
        },
        "runtime_mode": plan.runtime_mode,
        "enabled_modules": list(plan.enabled_modules),
        "module_configs": plan.module_configs,
        "retained_frontend_modules": list(plan.retained_frontend_modules),
        "retained_backend_apps": list(plan.retained_backend_apps),
        "removed_modules": list(plan.removed_modules),
        "retained_feature_behaviors": plan.retained_feature_behaviors,
        "module_dependency_graph": plan.module_dependency_graph,
        "module_feature_contracts": plan.module_feature_contracts,
        "prunable_route_paths": list(plan.prunable_route_paths),
        "prunable_permission_codes": list(plan.prunable_permission_codes),
        "seed_data_requirements": plan.seed_data_requirements,
        "support_dependencies": plan.support_dependencies,
        "exported_config_files": list(plan.exported_config_files),
    }


def build_generation_plan(
    blueprint_version: SystemBlueprintVersion | None = None,
    *,
    normalized_config: dict | None = None,
    runtime_mode: str | None = None,
) -> GenerationPlan:
    if blueprint_version is None and normalized_config is None:
        raise ValueError("build_generation_plan 需要 blueprint_version 或 normalized_config")

    if normalized_config is not None:
        normalized = validate_blueprint_config(normalized_config)
    elif blueprint_version is not None:
        normalized = validate_blueprint_config(blueprint_version.config_json)
    else:
        raise ValueError("build_generation_plan 需要 blueprint_version 或 normalized_config")

    resolved_runtime_mode = runtime_mode or resolve_runtime_mode(normalized)
    registry = {module.key: module for module in (*get_core_modules(), *get_business_modules())}
    requested = set(RUNTIME_BASE_MODULE_KEYS)
    requested.update(normalized.get("enabled_modules", []))

    resolved: set[str] = set()

    def visit(module_key: str) -> None:
        if module_key in resolved or module_key not in registry:
            return
        for dependency in registry[module_key].depends_on:
            visit(dependency)
        resolved.add(module_key)

    for module_key in sorted(requested):
        visit(module_key)

    ordered_modules = tuple(
        PlannedModule(
            key=module.key,
            label=module.label,
            django_app=module.django_app,
            api_prefix=module.api_prefix,
            depends_on=module.depends_on,
            frontend_module_key=_to_frontend_module_key(module.key),
        )
        for module in (*get_core_modules(), *get_business_modules())
        if module.key in resolved
    )
    retained_frontend_modules = _resolve_frontend_modules(resolved)
    removed_modules = tuple(sorted(set(registry.keys()) - resolved - {"generation"}))
    retained_feature_behaviors = resolve_feature_plan(normalized)
    module_dependency_graph = {
        module.key: {
            "depends_on": list(module.depends_on),
            "export_requires": list(registry[module.key].export_metadata.get("export_requires", module.depends_on)),
            "must_export_with": list(registry[module.key].export_metadata.get("must_export_with", ())),
        }
        for module in ordered_modules
    }
    module_feature_contracts = _build_module_feature_contracts(
        ordered_modules=ordered_modules,
        registry=registry,
        normalized=normalized,
    )
    prunable_route_paths = tuple(
        sorted(
            {
                route_path
                for contract in module_feature_contracts.values()
                for route_path in contract.get("prunable_route_paths", [])
            }
        )
    )
    prunable_permission_codes = tuple(
        sorted(
            {
                permission_code
                for contract in module_feature_contracts.values()
                for permission_code in contract.get("prunable_permission_codes", [])
            }
        )
    )
    seed_data_requirements = {
        module_key: contract["seed_data"]
        for module_key, contract in module_feature_contracts.items()
        if contract.get("seed_data", {}).get("required")
    }
    support_dependencies = {
        module_key: {
            "attachments_dependency": contract.get("attachments_dependency", False),
            "task_log_dependency": contract.get("task_log_dependency", False),
        }
        for module_key, contract in module_feature_contracts.items()
    }

    if resolved_runtime_mode == "SAAS":
        steps = (
            "validate_blueprint_version",
            "resolve_module_dependencies",
            "resolve_feature_behaviors",
            "provision_tenant_runtime",
            "create_system_instance",
            "record_generation_audit",
        )
    else:
        steps = (
            "validate_blueprint_version",
            "resolve_module_dependencies",
            "resolve_feature_behaviors",
            "collect_source_package",
            "write_manifest_lock",
            "build_zip_artifact",
            "record_generation_audit",
        )

    draft_manifest = {
        "runtime_mode": resolved_runtime_mode,
        "enabled_modules": list(normalized["enabled_modules"]),
        "retained_frontend_modules": list(retained_frontend_modules),
        "retained_backend_apps": [module.django_app for module in ordered_modules],
        "removed_modules": list(removed_modules),
        "retained_feature_behaviors": retained_feature_behaviors,
        "module_dependency_graph": module_dependency_graph,
        "module_feature_contracts": module_feature_contracts,
        "prunable_route_paths": list(prunable_route_paths),
        "prunable_permission_codes": list(prunable_permission_codes),
        "seed_data_requirements": seed_data_requirements,
        "support_dependencies": support_dependencies,
        "exported_config_files": list(EXPORT_CONFIG_FILES),
    }

    plan = GenerationPlan(
        runtime_mode=resolved_runtime_mode,
        enabled_modules=tuple(normalized["enabled_modules"]),
        module_configs=normalized["module_configs"],
        module_keys=tuple(module.key for module in ordered_modules),
        modules=ordered_modules,
        retained_frontend_modules=retained_frontend_modules,
        retained_backend_apps=tuple(module.django_app for module in ordered_modules),
        removed_modules=removed_modules,
        retained_feature_behaviors=retained_feature_behaviors,
        module_dependency_graph=module_dependency_graph,
        module_feature_contracts=module_feature_contracts,
        prunable_route_paths=prunable_route_paths,
        prunable_permission_codes=prunable_permission_codes,
        seed_data_requirements=seed_data_requirements,
        support_dependencies=support_dependencies,
        exported_config_files=EXPORT_CONFIG_FILES,
        export_manifest=draft_manifest,
        steps=steps,
    )
    if blueprint_version is None:
        return plan
    return GenerationPlan(
        runtime_mode=plan.runtime_mode,
        enabled_modules=plan.enabled_modules,
        module_configs=plan.module_configs,
        module_keys=plan.module_keys,
        modules=plan.modules,
        retained_frontend_modules=plan.retained_frontend_modules,
        retained_backend_apps=plan.retained_backend_apps,
        removed_modules=plan.removed_modules,
        retained_feature_behaviors=plan.retained_feature_behaviors,
        module_dependency_graph=plan.module_dependency_graph,
        module_feature_contracts=plan.module_feature_contracts,
        prunable_route_paths=plan.prunable_route_paths,
        prunable_permission_codes=plan.prunable_permission_codes,
        seed_data_requirements=plan.seed_data_requirements,
        support_dependencies=plan.support_dependencies,
        exported_config_files=plan.exported_config_files,
        export_manifest=build_export_manifest(blueprint_version=blueprint_version, plan=plan),
        steps=plan.steps,
    )


def _to_frontend_module_key(module_key: str) -> str | None:
    if module_key in FRONTEND_MODULE_KEY_MAP:
        return FRONTEND_MODULE_KEY_MAP[module_key]
    if module_key in {"organization", "configuration", "tenant", "blueprints", "generation"}:
        return None
    return module_key


def _resolve_frontend_modules(module_keys: set[str]) -> tuple[str, ...]:
    frontend_modules = set(EXPORT_BASE_FRONTEND_MODULES)
    for module_key in module_keys:
        frontend_key = _to_frontend_module_key(module_key)
        if frontend_key:
            frontend_modules.add(frontend_key)
    return tuple(sorted(frontend_modules))


def _build_module_feature_contracts(*, ordered_modules, registry: dict, normalized: dict) -> dict:
    contracts = {}
    module_configs = normalized.get("module_configs", {})
    for planned_module in ordered_modules:
        definition = registry[planned_module.key]
        metadata = definition.export_metadata or {}
        configured_features = module_configs.get(planned_module.key, {}).get("features", {})
        feature_pruning = metadata.get("feature_pruning", {})
        frontend_feature_pages = metadata.get("frontend_feature_pages", {})
        feature_keys = tuple(sorted(set(configured_features.keys()) | set(feature_pruning.keys()) | set(frontend_feature_pages.keys())))
        feature_contracts = {}
        prunable_features = []
        disabled_prunable_features = []
        config_only_features = []
        prunable_route_paths = set()
        prunable_permission_codes = set()

        for feature_key in feature_keys:
            pruning_meta = feature_pruning.get(feature_key, {})
            route_paths = tuple(
                pruning_meta.get("frontend_pages")
                or frontend_feature_pages.get(feature_key, ())
            )
            permission_codes = tuple(pruning_meta.get("permission_codes", ()))
            enabled = bool(configured_features.get(feature_key, False))
            capability = _resolve_feature_capability(feature_key=feature_key, pruning_meta=pruning_meta)
            contract = {
                "enabled": enabled,
                "capability": capability,
                "config_only": capability == "config_only",
                "code_prunable": bool(pruning_meta.get("code_prunable", False)),
                "ui_prunable": bool(pruning_meta.get("ui_prunable", False)),
                "route_paths": list(route_paths),
                "permission_codes": list(permission_codes),
            }
            feature_contracts[feature_key] = contract

            if capability == "config_only":
                config_only_features.append(feature_key)
                continue

            prunable_features.append(feature_key)
            if not enabled:
                disabled_prunable_features.append(feature_key)
                prunable_route_paths.update(route_paths)
                prunable_permission_codes.update(permission_codes)

        contracts[planned_module.key] = {
            "frontend_module_key": planned_module.frontend_module_key,
            "module_dependencies": list(definition.depends_on),
            "export_requires": list(metadata.get("export_requires", definition.depends_on)),
            "must_export_with": list(metadata.get("must_export_with", ())),
            "has_frontend_pages": bool(metadata.get("has_frontend_pages", planned_module.frontend_module_key is not None)),
            "feature_toggles": feature_contracts,
            "prunable_features": sorted(prunable_features),
            "disabled_prunable_features": sorted(disabled_prunable_features),
            "config_only_features": sorted(config_only_features),
            "prunable_route_paths": sorted(prunable_route_paths),
            "prunable_permission_codes": sorted(prunable_permission_codes),
            "seed_data": metadata.get("seed_data", {"required": False, "keys": ()}),
            "attachments_dependency": bool(metadata.get("attachments_dependency", False)),
            "task_log_dependency": bool(metadata.get("task_log_dependency", False)),
        }
    return contracts


def _resolve_feature_capability(*, feature_key: str, pruning_meta: dict) -> str:
    if pruning_meta.get("config_only"):
        return "config_only"
    if (
        pruning_meta.get("code_prunable")
        or pruning_meta.get("ui_prunable")
        or pruning_meta.get("frontend_pages")
        or pruning_meta.get("permission_codes")
    ):
        return "prunable"
    return "config_only"
