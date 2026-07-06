from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="configuration",
    label="运行时配置",
    django_app="core_apps.configuration",
    api_prefix="api/configuration/",
    depends_on=("system",),
    menus=(),
    permissions=(),
    features=("配置结构校验", "模块配置解析", "字段规则解析", "默认值解析"),
    workflows=("蓝图配置校验", "模块配置解析"),
    field_rules=(),
    default_rules=(),
    public_services=(
        "core_apps.configuration.services.ConfigurationService",
        "core_apps.configuration.validators.validate_blueprint_config",
    ),
)
