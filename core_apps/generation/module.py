from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="generation",
    label="生成任务",
    django_app="core_apps.generation",
    api_prefix="api/generation/",
    depends_on=("blueprints", "tenant", "configuration"),
    menus=(),
    permissions=(),
    features=("生成校验", "依赖解析", "SaaS 实例生成", "代码导出打包", "产物下载", "任务审计"),
    workflows=("蓝图版本生成", "代码导出重试", "产物下载与审计"),
    field_rules=(),
    default_rules=(),
    public_services=(
        "core_apps.generation.services.GenerationService",
        "core_apps.generation.validators.validate_blueprint_version_for_generation",
        "core_apps.generation.planners.build_generation_plan",
    ),
)
