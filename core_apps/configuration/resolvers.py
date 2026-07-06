from __future__ import annotations

from .catalog import MODULE_CONFIGURATION_CATALOG
from .validators import validate_blueprint_config


def build_empty_config() -> dict:
    return {
        "basic": {},
        "enabled_modules": [],
        "module_configs": {},
    }


def resolve_module_config_from_snapshot(config_json: dict, module_key: str) -> dict:
    normalized = validate_blueprint_config(config_json)
    return normalized["module_configs"].get(
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
