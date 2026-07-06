from core_apps.modules.registry import ModuleDefinition


MODULE = ModuleDefinition(
    key="authentication",
    label="认证与授权",
    django_app="core_apps.authentication",
    api_prefix="api/auth/",
    depends_on=("organization",),
    permissions=(),
    menus=(),
    features=("登录", "JWT 刷新", "用户角色权限"),
    workflows=("登录鉴权", "当前用户信息下发"),
    field_rules=(),
    default_rules=(),
    public_services=(),
)
