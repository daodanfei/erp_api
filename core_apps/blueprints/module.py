from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="blueprints",
    label="ERP 蓝图",
    django_app="core_apps.blueprints",
    api_prefix="api/blueprints/",
    depends_on=("system", "configuration"),
    menus=(),
    permissions=(),
    features=("蓝图管理", "蓝图版本管理", "发布快照"),
    workflows=("蓝图版本发布", "蓝图版本克隆", "基于版本创建 SaaS 实例"),
    field_rules=(),
    default_rules=(),
    public_services=(
        "core_apps.blueprints.services.BlueprintService",
        "core_apps.blueprints.services.SystemInstanceService",
        "core_apps.blueprints.services.GenerationJobService",
    ),
)
