from __future__ import annotations

from dataclasses import dataclass

from rest_framework import serializers

from core_apps.blueprints.models import SystemBlueprintVersion
from core_apps.configuration import validate_blueprint_config
from core_apps.modules import get_business_modules, get_core_modules

from .planners import resolve_runtime_mode


FEATURE_MODULE_REQUIREMENTS = {
    ("purchase", "receipt_auto_ap"): ("ap_payable",),
    ("sales", "outbound_auto_ar"): ("ar_receivable",),
    ("sales", "credit_control"): ("finance",),
    ("accounting", "ar_ap_posting_enabled"): ("ar_receivable", "ap_payable"),
    ("accounting", "inventory_posting_enabled"): ("inventory",),
}
REQUIRED_DEFAULTS = {
    "purchase": ("default_currency",),
    "sales": ("default_currency",),
    "supplier": ("default_currency",),
    "finance": ("default_currency",),
}
APPROVAL_FIELD_RULES = {
    "purchase": {
        "feature": "approval",
        "workflow": "purchase_order_submit",
        "approval_field": "purchase_order.approver",
    },
    "sales": {
        "feature": "approval",
        "workflow": "sales_order_submit",
        "approval_field": "sales_order.approver",
    },
}


@dataclass(frozen=True, slots=True)
class GenerationValidationResult:
    blueprint_version: SystemBlueprintVersion
    runtime_mode: str
    normalized_config: dict
    resolved_module_keys: tuple[str, ...]


def validate_blueprint_version_for_generation(
    *,
    blueprint_version: SystemBlueprintVersion | None,
    runtime_mode: str | None = None,
    require_published: bool = True,
) -> GenerationValidationResult:
    if blueprint_version is None:
        raise serializers.ValidationError("蓝图版本不存在")
    if blueprint_version.pk is None:
        raise serializers.ValidationError("蓝图版本不存在")

    normalized = validate_blueprint_config(blueprint_version.config_json)
    requested_runtime_mode = runtime_mode or resolve_runtime_mode(normalized)
    if requested_runtime_mode not in {"SAAS", "CODE_EXPORT"}:
        raise serializers.ValidationError("runtime_mode 仅支持 SAAS 或 CODE_EXPORT")
    if not normalized["enabled_modules"]:
        raise serializers.ValidationError("蓝图版本至少需要启用一个模块后才能生成")
    if require_published and not blueprint_version.is_published:
        raise serializers.ValidationError("仅允许对已发布蓝图版本发起生成")

    config_runtime_mode = resolve_runtime_mode(normalized)
    if requested_runtime_mode != config_runtime_mode:
        raise serializers.ValidationError(
            f"当前蓝图模式为 {config_runtime_mode}，不支持按 {requested_runtime_mode} 发起生成"
        )

    errors: dict[str, list[str]] = {}
    enabled_modules = tuple(normalized["enabled_modules"])
    registry = {module.key: module for module in (*get_core_modules(), *get_business_modules())}

    _validate_module_dependencies(enabled_modules=enabled_modules, registry=registry, errors=errors)
    _validate_feature_dependencies(normalized_config=normalized, enabled_modules=enabled_modules, errors=errors)
    _validate_required_defaults(normalized_config=normalized, errors=errors)
    _validate_single_warehouse_defaults(normalized_config=normalized, errors=errors)
    _validate_approval_configuration(normalized_config=normalized, errors=errors)

    if errors:
        raise serializers.ValidationError(errors)

    return GenerationValidationResult(
        blueprint_version=blueprint_version,
        runtime_mode=requested_runtime_mode,
        normalized_config=normalized,
        resolved_module_keys=enabled_modules,
    )


def _validate_module_dependencies(*, enabled_modules: tuple[str, ...], registry: dict, errors: dict[str, list[str]]) -> None:
    enabled = set(enabled_modules)
    for module_key in enabled_modules:
        module = registry.get(module_key)
        if module is None:
            continue
        missing = sorted(dependency for dependency in module.depends_on if dependency not in enabled)
        if missing:
            errors.setdefault("module_dependencies", []).append(
                f"{module_key} 缺少依赖模块: {', '.join(missing)}"
            )


def _validate_feature_dependencies(*, normalized_config: dict, enabled_modules: tuple[str, ...], errors: dict[str, list[str]]) -> None:
    enabled = set(enabled_modules)
    for (module_key, feature_key), required_modules in FEATURE_MODULE_REQUIREMENTS.items():
        module_config = normalized_config["module_configs"].get(module_key, {})
        if not module_config.get("features", {}).get(feature_key):
            continue
        missing = sorted(required_module for required_module in required_modules if required_module not in enabled)
        if missing:
            errors.setdefault("feature_dependencies", []).append(
                f"{module_key}.{feature_key} 缺少依赖模块: {', '.join(missing)}"
            )


def _validate_required_defaults(*, normalized_config: dict, errors: dict[str, list[str]]) -> None:
    for module_key, default_keys in REQUIRED_DEFAULTS.items():
        if module_key not in normalized_config["enabled_modules"]:
            continue
        defaults = normalized_config["module_configs"].get(module_key, {}).get("defaults", {})
        for default_key in default_keys:
            value = defaults.get(default_key)
            if not isinstance(value, str) or not value.strip():
                errors.setdefault("required_defaults", []).append(
                    f"{module_key}.defaults.{default_key} 为必填"
                )


def _validate_single_warehouse_defaults(*, normalized_config: dict, errors: dict[str, list[str]]) -> None:
    if "inventory" not in normalized_config["enabled_modules"]:
        return
    inventory_config = normalized_config["module_configs"].get("inventory", {})
    features = inventory_config.get("features", {})
    multi_warehouse = bool(features.get("multi_warehouse"))
    warehouse_required = bool(features.get("warehouse_required_on_transaction"))
    if multi_warehouse or warehouse_required:
        return
    default_warehouse_code = inventory_config.get("defaults", {}).get("default_warehouse_code")
    if not isinstance(default_warehouse_code, str) or not default_warehouse_code.strip():
        errors.setdefault("inventory_defaults", []).append("单仓模式必须定义 inventory.defaults.default_warehouse_code")


def _validate_approval_configuration(*, normalized_config: dict, errors: dict[str, list[str]]) -> None:
    for module_key, rule in APPROVAL_FIELD_RULES.items():
        if module_key not in normalized_config["enabled_modules"]:
            continue
        module_config = normalized_config["module_configs"].get(module_key, {})
        features = module_config.get("features", {})
        workflows = module_config.get("workflows", {})
        field_rules = module_config.get("field_rules", {})
        approval_enabled = bool(features.get(rule["feature"]))
        workflow_value = workflows.get(rule["workflow"])
        approval_field = field_rules.get(rule["approval_field"], {})

        if not approval_enabled and workflow_value == "manual_approve":
            errors.setdefault("approval_rules", []).append(
                f"{module_key} 已关闭审批，不能继续使用 {rule['workflow']}=manual_approve"
            )

        if not approval_enabled and approval_field:
            if approval_field.get("visible") or approval_field.get("required"):
                errors.setdefault("approval_rules", []).append(
                    f"{module_key} 已关闭审批，{rule['approval_field']} 不能仍然可见或必填"
                )
