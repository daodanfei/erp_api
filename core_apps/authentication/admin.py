from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Permission, Role, User


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "type", "parent", "status", "order")
    list_filter = ("type", "status")
    search_fields = ("name", "code", "path", "component")
    ordering = ("order", "id")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "data_scope", "status")
    list_filter = ("data_scope", "status")
    search_fields = ("name", "code")
    filter_horizontal = ("permissions",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "dept",
        "is_staff",
        "is_superuser",
        "is_active",
        "status",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "status", "roles")
    search_fields = ("username", "email", "first_name", "last_name", "phone")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("ERP 信息", {"fields": ("dept", "roles", "phone", "status")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("ERP 信息", {"fields": ("dept", "roles", "phone", "status")}),
    )
    filter_horizontal = ("groups", "user_permissions", "roles")


admin.site.site_header = "TWC ERP 管理后台"
admin.site.site_title = "TWC ERP Admin"
admin.site.index_title = "系统数据管理"


PROJECT_APP_LABELS = (
    "organization",
    "system",
    "inventory",
    "crm",
    "sales",
    "supplier",
    "purchase",
    "supply_chain",
    "reports",
    "platform",
    "ar_receivable",
    "ap_payable",
    "finance",
    "accounting",
)


for app_label in PROJECT_APP_LABELS:
    app_config = apps.get_app_config(app_label)
    for model in app_config.get_models():
        if model in {Permission, Role, User} or model._meta.auto_created:
            continue
        try:
            admin.site.register(model)
        except AlreadyRegistered:
            continue
