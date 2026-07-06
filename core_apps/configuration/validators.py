from __future__ import annotations

from rest_framework import serializers

from core_apps.modules import get_business_modules, get_core_modules

from .catalog import MODULE_CONFIGURATION_CATALOG
from .schemas import BLUEPRINT_BASIC_SCHEMA, BLUEPRINT_CONFIG_SCHEMA, MODULE_CONFIG_SCHEMA


FEATURE_MODULE_REQUIREMENTS = {
    ("purchase", "receipt_auto_ap"): ("ap_payable",),
    ("sales", "outbound_auto_ar"): ("ar_receivable",),
    ("sales", "credit_control"): ("finance",),
    ("accounting", "ar_ap_posting_enabled"): ("ar_receivable", "ap_payable"),
    ("accounting", "inventory_posting_enabled"): ("inventory",),
}


def _registered_module_keys() -> set[str]:
    modules = (*get_core_modules(), *get_business_modules())
    return {module.key for module in modules}


def _normalize_feature_dependencies(normalized: dict) -> None:
    enabled_modules = set(normalized["enabled_modules"])
    for (module_key, feature_key), required_modules in FEATURE_MODULE_REQUIREMENTS.items():
        module_config = normalized["module_configs"].get(module_key)
        if module_config is None:
            continue
        if any(required_module not in enabled_modules for required_module in required_modules):
            module_config.setdefault("features", {})[feature_key] = False


def validate_blueprint_config(config: dict | None) -> dict:
    if not isinstance(config, dict):
        raise serializers.ValidationError("config_json 必须是对象")

    normalized = {
        "basic": config.get("basic") or {},
        "enabled_modules": config.get("enabled_modules") or [],
        "module_configs": config.get("module_configs") or {},
    }

    for key, expected_type in BLUEPRINT_CONFIG_SCHEMA.items():
        if not isinstance(normalized[key], expected_type):
            raise serializers.ValidationError(f"{key} 类型不正确")

    basic = normalized["basic"]
    for required_key, expected_type in BLUEPRINT_BASIC_SCHEMA.items():
        value = basic.get(required_key)
        if value is None:
            raise serializers.ValidationError(f"basic.{required_key} 为必填")
        if not isinstance(value, expected_type) or (isinstance(value, str) and not value.strip()):
            raise serializers.ValidationError(f"basic.{required_key} 类型不正确")

    mode = basic["mode"]
    if mode not in {"saas", "code_export"}:
        raise serializers.ValidationError("basic.mode 仅支持 saas 或 code_export")

    module_keys = _registered_module_keys()
    enabled_modules = normalized["enabled_modules"]
    if len(enabled_modules) != len(set(enabled_modules)):
        raise serializers.ValidationError("enabled_modules 不能重复")
    unknown_enabled = sorted(set(enabled_modules) - module_keys)
    if unknown_enabled:
        raise serializers.ValidationError(f"enabled_modules 包含未知模块: {', '.join(unknown_enabled)}")

    module_configs = normalized["module_configs"]
    unknown_config_keys = sorted(set(module_configs.keys()) - module_keys)
    if unknown_config_keys:
        raise serializers.ValidationError(f"module_configs 包含未知模块: {', '.join(unknown_config_keys)}")

    for module_key, module_config in module_configs.items():
        if not isinstance(module_config, dict):
            raise serializers.ValidationError(f"module_configs.{module_key} 必须是对象")
        template = MODULE_CONFIGURATION_CATALOG.get(module_key, {})
        for field_name, expected_type in MODULE_CONFIG_SCHEMA.items():
            template_section = template.get(field_name, {})
            raw_section = module_config.get(field_name, {})
            if raw_section is None:
                raw_section = {}
            if not isinstance(raw_section, expected_type):
                raise serializers.ValidationError(f"module_configs.{module_key}.{field_name} 类型不正确")
            section = {**template_section, **raw_section}
            normalized["module_configs"].setdefault(module_key, {})[field_name] = section
            if not isinstance(section, expected_type):
                raise serializers.ValidationError(f"module_configs.{module_key}.{field_name} 类型不正确")

        field_rules = normalized["module_configs"][module_key].get("field_rules", {})
        for field_key, field_rule in field_rules.items():
            if not isinstance(field_rule, dict):
                raise serializers.ValidationError(f"module_configs.{module_key}.field_rules.{field_key} 必须是对象")
            for attr in ("visible", "required", "readonly"):
                if attr in field_rule and not isinstance(field_rule[attr], bool):
                    raise serializers.ValidationError(
                        f"module_configs.{module_key}.field_rules.{field_key}.{attr} 必须是布尔值"
                    )

    for module_key in enabled_modules:
        normalized["module_configs"].setdefault(
            module_key,
            MODULE_CONFIGURATION_CATALOG.get(
                module_key,
                {
                    "features": {},
                    "workflows": {},
                    "field_rules": {},
                    "defaults": {},
                },
            ),
        )

    _normalize_feature_dependencies(normalized)

    return normalized
