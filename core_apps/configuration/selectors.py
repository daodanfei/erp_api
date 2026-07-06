from .services import ConfigurationService


def resolve_module_config(runtime_config, module_key: str) -> dict:
    return ConfigurationService.resolve_module_config(runtime_config, module_key)


def is_feature_enabled(runtime_config, module_key: str, feature_key: str) -> bool:
    return ConfigurationService.is_feature_enabled(runtime_config, module_key, feature_key)


def get_workflow(runtime_config, module_key: str, workflow_key: str, default=None):
    return ConfigurationService.get_workflow(runtime_config, module_key, workflow_key, default=default)


def get_field_rule(runtime_config, module_key: str, field_key: str, default=None):
    return ConfigurationService.get_field_rule(runtime_config, module_key, field_key, default=default)


def get_default_value(runtime_config, module_key: str, key: str, default=None):
    return ConfigurationService.get_default_value(runtime_config, module_key, key, default=default)
