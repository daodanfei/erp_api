BLUEPRINT_CONFIG_SCHEMA = {
    "basic": dict,
    "enabled_modules": list,
    "module_configs": dict,
}

BLUEPRINT_BASIC_SCHEMA = {
    "name": str,
    "industry": str,
    "mode": str,
}

MODULE_CONFIG_SCHEMA = {
    "features": dict,
    "workflows": dict,
    "field_rules": dict,
    "defaults": dict,
}
