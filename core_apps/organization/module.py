from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="organization",
    label="组织架构",
    django_app="core_apps.organization",
    api_prefix="api/org/",
    depends_on=(),
    permissions=(),
    menus=(),
    features=("部门组织",),
    workflows=("组织树维护",),
    field_rules=(),
    default_rules=(),
    public_services=(),
)
