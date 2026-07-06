from django.conf import settings
from django.db import models


class Tenant(models.Model):
    STATUS_CHOICES = (
        ("ACTIVE", "启用"),
        ("INACTIVE", "停用"),
        ("ARCHIVED", "归档"),
    )

    code = models.CharField(max_length=100, unique=True, verbose_name="租户编码")
    name = models.CharField(max_length=100, verbose_name="租户名称")
    instance = models.ForeignKey(
        "blueprints.SystemInstance",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
        verbose_name="绑定实例",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE", verbose_name="状态")
    industry = models.CharField(max_length=100, blank=True, verbose_name="行业")
    user_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name="用户数上限")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "租户"
        verbose_name_plural = verbose_name
        ordering = ["name", "id"]
        db_table = "sys_tenants"

    def __str__(self):
        return f"{self.name}({self.code})"

    @property
    def active_config_snapshot(self):
        return self.config_snapshots.select_related("blueprint_version", "blueprint_version__blueprint").first()

    @property
    def active_blueprint_version(self):
        snapshot = self.active_config_snapshot
        return snapshot.blueprint_version if snapshot else None


class TenantUser(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships", verbose_name="租户")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
        verbose_name="用户",
    )
    is_owner = models.BooleanField(default=False, verbose_name="是否所有者")
    is_default = models.BooleanField(default=False, verbose_name="是否默认")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "租户成员"
        verbose_name_plural = verbose_name
        ordering = ["tenant_id", "user_id", "id"]
        db_table = "sys_tenant_users"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_tenant_user"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.user.username}"


class TenantModuleState(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="module_states", verbose_name="租户")
    module_key = models.CharField(max_length=100, verbose_name="模块标识")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")

    class Meta:
        verbose_name = "租户模块开关"
        verbose_name_plural = verbose_name
        ordering = ["tenant_id", "module_key"]
        db_table = "sys_tenant_module_states"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "module_key"], name="uniq_tenant_module_state"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.module_key}"


class TenantConfigSnapshot(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="config_snapshots", verbose_name="租户")
    blueprint_version = models.ForeignKey(
        "blueprints.SystemBlueprintVersion",
        on_delete=models.PROTECT,
        related_name="tenant_snapshots",
        verbose_name="蓝图版本",
    )
    config_json = models.JSONField(default=dict, blank=True, verbose_name="配置快照")
    applied_at = models.DateTimeField(auto_now_add=True, verbose_name="应用时间")

    class Meta:
        verbose_name = "租户配置快照"
        verbose_name_plural = verbose_name
        ordering = ["-applied_at", "-id"]
        db_table = "sys_tenant_config_snapshots"

    def __str__(self):
        return f"{self.tenant.code}@{self.blueprint_version.version}"
