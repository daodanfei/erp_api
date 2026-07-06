from __future__ import annotations

from .catalog import MODULE_CONFIGURATION_CATALOG
from .resolvers import build_empty_config, resolve_module_config_from_snapshot
from .validators import validate_blueprint_config


class ConfigurationService:
    @staticmethod
    def build_empty_config() -> dict:
        return build_empty_config()

    @staticmethod
    def get_module_configuration_catalog() -> dict:
        return MODULE_CONFIGURATION_CATALOG

    @staticmethod
    def validate_blueprint_config(config: dict | None) -> dict:
        return validate_blueprint_config(config)

    @staticmethod
    def resolve_module_config(runtime_config, module_key: str) -> dict:
        return resolve_module_config_from_snapshot(runtime_config.config_json, module_key)

    @staticmethod
    def is_feature_enabled(runtime_config, module_key: str, feature_key: str) -> bool:
        module_config = ConfigurationService.resolve_module_config(runtime_config, module_key)
        return bool(module_config.get("features", {}).get(feature_key, False))

    @staticmethod
    def get_workflow(runtime_config, module_key: str, workflow_key: str, default=None):
        module_config = ConfigurationService.resolve_module_config(runtime_config, module_key)
        return module_config.get("workflows", {}).get(workflow_key, default)

    @staticmethod
    def get_field_rule(runtime_config, module_key: str, field_key: str, default=None):
        module_config = ConfigurationService.resolve_module_config(runtime_config, module_key)
        return module_config.get("field_rules", {}).get(field_key, default)

    @staticmethod
    def get_default_value(runtime_config, module_key: str, key: str, default=None):
        module_config = ConfigurationService.resolve_module_config(runtime_config, module_key)
        return module_config.get("defaults", {}).get(key, default)
