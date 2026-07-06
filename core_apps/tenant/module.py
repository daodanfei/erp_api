from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="tenant",
    label="租户中心",
    django_app="core_apps.tenant",
    api_prefix="api/tenant/",
    depends_on=("blueprints", "configuration"),
    menus=(),
    permissions=(),
    features=("租户管理", "租户配置应用", "运行时上下文"),
    workflows=("从蓝图版本创建租户", "应用蓝图版本到租户"),
    field_rules=(),
    default_rules=(),
    public_services=(
        "core_apps.tenant.services.TenantService",
        "core_apps.tenant.services.build_runtime_config",
        "core_apps.tenant.services.resolve_user_tenant",
    ),
)
